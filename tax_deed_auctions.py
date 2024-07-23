from typing import Any, Optional, Sequence, Text, TypedDict, cast
import selenium
import selenium.common
import selenium.webdriver
import selenium.webdriver.remote
import selenium.webdriver.remote.webelement
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.remote import webelement
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions
import time
import json
import os
import threading

from selenium.webdriver.chrome.options import Options

chrome_options = Options()
# chrome_options.add_argument("--headless")
# chrome_options.add_argument("--window-size=1920,1080")
# chrome_options.add_argument("--disable-gpu")
driver = selenium.webdriver.Chrome(ChromeDriverManager().install(), chrome_options=chrome_options)

# driver = selenium.webdriver.Chrome(
#     ChromeDriverManager().install()
# )
SQUARE_FEET_IN_ACRE = 43560

county_calendar_links = [
    "https://marion.realtaxdeed.com/index.cfm?zaction=USER&zmethod=CALENDAR",
    # "https://www.polk.realtaxdeed.com/index.cfm?zaction=USER&zmethod=CALENDAR",
]

for link in county_calendar_links:
    link_with_no_prefix = link.replace("https://", "").replace("www.", "")
    subdomain_period = link_with_no_prefix.index(".")
    if subdomain_period == -1:
        raise Exception("Error no subdomain period.")
    county_name = link_with_no_prefix[:subdomain_period].upper()

    driver.get(link)
    driver_waiter = WebDriverWait(driver=driver, timeout=10)

    try:
        current_month_calendar_elements = cast(
            Sequence[webelement.WebElement],
            driver_waiter.until(
                method=expected_conditions.presence_of_all_elements_located(
                    (By.CLASS_NAME, "CALSELT")
                ),
                message="Did not find all elements."
            )
        )
    except Exception as e:
        continue

    def create_tax_deed_auction_day_link(formatted_date: Text) -> Text:
        current_url_origin = cast(Text, driver.execute_script("return window.location.origin;"))
        return "{}/index.cfm?zaction=AUCTION&Zmethod=PREVIEW&AUCTIONDATE={}".format(current_url_origin, formatted_date)

    class MissingDayIdException(Exception):
        pass

    tax_deed_sale_auction_day_links: Sequence[Text] = []

    for auction_div in current_month_calendar_elements:
        try:
            day_id = auction_div.get_attribute("dayid")
            if not day_id:
                raise MissingDayIdException("There was no day_id: {}".format(auction_div))
            tax_deed_sale_auction_day_links.append(
                (
                    day_id,
                    create_tax_deed_auction_day_link(day_id)
                )
            )
        except Exception as e:
            print("ERR")
            exit()

    try:
        time.sleep(2)
        month_view_switch_buttons = cast(
            Sequence[webelement.WebElement],
            driver_waiter.until(
                method=expected_conditions.presence_of_all_elements_located(
                    (By.CLASS_NAME, "CALNAV")
                ),
                message="Did not find all elements."
            )
        )
        next_month_buttons = filter(lambda web_element: ("next month" in web_element.find_element(By.TAG_NAME, "a").get_attribute("aria-label").lower()), month_view_switch_buttons)
        if not next_month_buttons:
            raise Exception("No next month button found??")
        else:
            next_month_button = next(iter(next_month_buttons))
            next_month_button.find_element(By.TAG_NAME, "a").click()

        print("On next calendar month...")
        time.sleep(2)
        next_month_calendar_elements = cast(
            Sequence[webelement.WebElement],
            driver_waiter.until(
                method=expected_conditions.presence_of_all_elements_located(
                    (By.CLASS_NAME, "CALSELT")
                ),
                message="Did not find all elements."
            )
        )
    except Exception as e:
        print(e)
        continue

    for auction_div in next_month_calendar_elements:
        try:
            day_id = auction_div.get_attribute("dayid")
            if not day_id:
                raise MissingDayIdException("There was no day_id: {}".format(auction_div))
            tax_deed_sale_auction_day_links.append(
                (
                    day_id,
                    create_tax_deed_auction_day_link(day_id)
                )
            )
        except Exception as e:
            print("ERR")
            exit()

    tax_deed_parcel_infos = []
    for day_id, day_link in tax_deed_sale_auction_day_links:
        driver.get(day_link)
        auction_day_link_waiter = WebDriverWait(driver, timeout=10)

        try:
            total_pages_element = cast(
                webelement.WebElement,
                auction_day_link_waiter.until(
                    method=expected_conditions.visibility_of_all_elements_located(
                        locator=(By.ID, "maxWA")
                    )
                )[0]
            )
        except selenium.common.exceptions.TimeoutException as e:
            print("There were no running auctions on day {} in {} county... going onto the next day".format(day_id, county_name))
            continue
        print(total_pages_element.text, "pages")

        try:
            next_page_element = cast(
                webelement.WebElement,
                auction_day_link_waiter.until(
                    method=expected_conditions.visibility_of_all_elements_located(
                        locator=(By.CLASS_NAME, "PageRight")
                    )
                )[0]
            )
        except Exception as e:
            continue

        if total_pages_element is None or total_pages_element == False:
            continue

        total_pages = int(total_pages_element.text)
        if total_pages == 0:
            print("There are no pages! Moving on...")
            continue

        auction_day_tax_deed_records = []
        for _ in range(total_pages):
            try:
                current_active_auction_tax_deed_records_container = cast(
                    webelement.WebElement,
                    auction_day_link_waiter.until(
                        method=expected_conditions.visibility_of_element_located(
                            locator=(By.ID, "Area_W")
                        )
                    )
                )
            except Exception as e:
                continue

            time.sleep(3)
            unclean_current_active_auction_tax_deed_records = current_active_auction_tax_deed_records_container.find_elements(By.CLASS_NAME, "AUCTION_DETAILS")

            clean_current_active_auction_tax_deed_records = []
            for auction_details_element in unclean_current_active_auction_tax_deed_records:
                header_label_elements = auction_details_element.find_elements(By.TAG_NAME, "th")
                data_value_elements = auction_details_element.find_elements(By.TAG_NAME, "td")

                if len(header_label_elements) != len(data_value_elements):
                    raise Exception("Mismatch in length of header / labels and data values...")

                def create_key_from_label(label: Text) -> Text:
                    key = label.replace(":", "").replace("#", "number").lower().strip().replace(" ", "_")
                    return key

                keys = [
                    (
                        create_key_from_label(element.text)
                        if element.text else "property_address"
                    )
                    for element in header_label_elements
                ]
                values = [
                    element.text
                    for element in data_value_elements
                ]

                parcel_index = keys.index("parcel_id")
                if parcel_index != -1:
                    keys.append("parcel_link")
                    link_element = data_value_elements[parcel_index].find_element(By.TAG_NAME, "a")
                    if link_element is None:
                        raise Exception("There is no parcel link...")
                    values.append(link_element.get_attribute("href"))
                
                keys.append("day_id")
                values.append(day_id)
                tax_deed_record = {
                    k : v
                    for k, v in zip(keys, values)
                }

                clean_current_active_auction_tax_deed_records.append(tax_deed_record)


            auction_day_tax_deed_records.extend(clean_current_active_auction_tax_deed_records)
            time.sleep(2)
            next_page_element.click()
        
        tax_deed_parcel_infos.append(
            (day_id, auction_day_tax_deed_records)
        )
        time.sleep(1)

    by_day_info = {}
    for day_id, records in tax_deed_parcel_infos:
        print("{} sales scheduled for auction: {}".format(day_id, len(records)))
        print()
        print()
        print(records)
        print()
        print()
        by_day_info[day_id] = records
    
    for day_id, records in by_day_info.items():
        for record_index, record in enumerate(records):
            parcel_link = record["parcel_link"]
            parcel_id = record["parcel_id"]
            driver.get(parcel_link)
            time.sleep(2)

            if county_name == "MARION":
                try:
                    parcel_viewer_waiter = WebDriverWait(driver, timeout=10)
                    table_headers = cast(
                        Sequence[webelement.WebElement],
                        parcel_viewer_waiter.until(
                            method=expected_conditions.presence_of_all_elements_located(
                                (By.CLASS_NAME, "RowHeader")
                            )
                        )
                    )
                except Exception as e:
                    continue

                relevant_column_indexes = {}
                parcel_data = {}
                time.sleep(2)
                table_header = table_headers[2]
                table_column_label_elements = table_header.find_elements(By.TAG_NAME, "th")

                get_columns = ("front", "depth", "zoning")
                found_columns = set()
                for label_element in table_column_label_elements:
                    if label_element.text.lower() in get_columns:
                        found_columns.add(label_element.text.lower())

                found_correct_table = len(get_columns) == len(found_columns)
                if found_correct_table:
                    print(found_columns)
                    for column_index, column_tr in enumerate(table_header.find_elements(By.TAG_NAME, "th")):
                        if column_tr.text.lower() in map(lambda col_name: col_name.lower(), get_columns):
                            relevant_column_indexes[column_index] = column_tr.text.lower()
                    
                else:
                    class TableNotFoundException(Exception):
                        pass
                    raise TableNotFoundException("No table found for {}".format(county_name))


                table_parent = cast(webelement.WebElement, table_header.parent)
                table_data_rows = table_parent.find_elements(By.CLASS_NAME, "RowStyle")
                if len(table_data_rows) == 0:
                    class NoParcelDataFoundException(Exception):
                        pass
                    raise NoParcelDataFoundException("No parcel data entry found for {} in {} county".format(parcel_id, county_name))

                table_data_row = next(iter(filter(lambda row: len(row.find_elements(By.TAG_NAME, "td")) == 13, table_data_rows)))
                table_data_row_column_elements = table_data_row.find_elements(By.TAG_NAME, "td")

                for column_index, column_data_element in enumerate(table_data_row_column_elements):
                    if column_index in relevant_column_indexes:
                        parcel_data[relevant_column_indexes[column_index]] = column_data_element.text
                
                # Convert frontage and depth to sq_ft, and sq_ft into acres
                parcel_data["front"] = float(parcel_data["front"])
                parcel_data["depth"] = float(parcel_data["depth"])
                parcel_data["sq_ft"] = int(parcel_data["front"] * parcel_data["depth"])
                parcel_data["acres"] = round(parcel_data["sq_ft"] / SQUARE_FEET_IN_ACRE, 2)
                records[record_index] = {
                    **records[record_index],
                    **parcel_data
                }
                print(records[record_index])
            elif county_name == "POLK":
                pass

    desired_output_file_name = "tax_deeds_{}_county.json".format(county_name)
    if desired_output_file_name in os.listdir():
        os.remove(desired_output_file_name)

    with open(desired_output_file_name, "w+") as f:
        json.dump(
            obj=by_day_info,
            fp=f,
            ensure_ascii=True,
            indent=4
        )

driver.quit()