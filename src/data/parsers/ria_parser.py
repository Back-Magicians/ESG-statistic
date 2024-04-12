import asyncio
import csv
import re
import time
from datetime import datetime

import aiohttp
from selectolax.parser import HTMLParser
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BUTTON_XPATH = '//div[@class="list-more color-btn-second-hover"'
BUTTON = f'{BUTTON_XPATH} and contains(text(), "Еще 20 материалов")]'
CSV_HEADERS = ["Заголовок", "Компания", "Дата публикации", "Текст"]
RIA_URL = "https://ria.ru/organization_Sberbank_Rossii/"
TARGET_ARTICLE = (
    'Сбербанк не намерен участвовать в допэмиссии "Рублево-Архангельского" - Греф'
)
TEST_FILENAME = "ria_data.csv"


# Класс - инициализатор браузера Хрома для Selenium
class WebDriver:
    def __init__(self) -> None:
        self.options = Options()
        self.options.add_argument("--headless")
        self.options.add_argument("--window-size=1920x1080")
        self.driver = None

    def start_driver(self) -> None:
        self.driver = webdriver.Chrome(options=self.options)

    def stop_driver(self) -> None:
        if self.driver:
            self.driver.quit()


# Класс - сборщик URL-адресов на странице после прогрузки всей ленты
class UrlsCollector:
    def __init__(self, url: str, target_article_title: str) -> None:
        self.url = url
        self.target_article_title = target_article_title
        self.driver_manager = WebDriver()

    def collect_urls(self) -> list[str]:
        self.driver_manager.start_driver()
        driver = self.driver_manager.driver
        driver.get(self.url)

        urls = []

        scroll_complete = False
        button_clicked = False
        try:
            while not scroll_complete:
                self._scroll_to_bottom(driver)
                self._wait_for_load()

                if not button_clicked:
                    try:
                        self._click_more_button(driver)
                        button_clicked = True
                    except TimeoutException:
                        continue
                else:
                    pass

                try:
                    target_article = WebDriverWait(driver, 1).until(
                        EC.text_to_be_present_in_element(
                            (By.CSS_SELECTOR, "body"), TARGET_ARTICLE
                        )
                    )
                    scroll_complete = True
                    button_clicked = True
                except TimeoutException:
                    continue

                if target_article:
                    links = driver.find_elements(By.CSS_SELECTOR, "a.list-item__image")

                    for link in links:
                        href = link.get_attribute("href")
                        urls.append(href)
                    break

        except KeyboardInterrupt:
            pass
        finally:
            self.driver_manager.stop_driver()

        return urls

    def _scroll_to_bottom(self, driver: WebDriver) -> None:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

    def _wait_for_load(self) -> None:
        time.sleep(2)

    def _click_more_button(self, driver: WebDriver) -> None:
        more_button = WebDriverWait(driver, 1).until(
            EC.visibility_of_element_located((By.XPATH, BUTTON))
        )
        more_button.click()


# Класс - парсер страниц, находящихся по URL-адресам, полученным классом UrlsCollector
class DataParser:
    def __init__(self) -> None:
        self.session = aiohttp.ClientSession()

    async def close_session(self) -> None:
        await self.session.close()

    async def parse_data(self, urls: list[str]) -> list[dict[str, str]]:
        parsed_data = []
        last = len(urls)

        for url in urls:
            await asyncio.sleep(5)
            data = await self._parse_page(url)
            parsed_data.append(data)
            print(data)
            print(f"Осталось {last - 1} страниц")
            last -= 1

        return parsed_data

    async def _parse_page(self, url: str) -> dict[str, str]:
        async with self.session.get(url) as response:
            html_content = await response.text()
            html = HTMLParser(html_content)

            title = self._parse_title(html)
            publication_date = self._parse_date(html)
            article_text = self._parse_text(html)

            if article_text == "":
                return

            return {
                "Заголовок": title,
                "Компания": "Сбербанк",
                "Дата публикации": publication_date,
                "Текст": article_text,
            }

    def _parse_title(self, html: HTMLParser) -> str:
        title_element = html.css_first(".article__title")

        if title_element:
            return title_element.text().replace("\xa0", " ")

        return ""

    def _parse_date(self, html: HTMLParser) -> str:
        date_element = html.css_first(".article__info-valign").text().strip()

        if date_element:
            parsed_date = re.findall(r"\d{2}.\d{2}.\d{4}", date_element)

            return parsed_date[0]

        return ""

    def _parse_text(self, html: HTMLParser) -> str:
        content_block = html.css_first(".layout-article__main-over")
        article_text = ""

        paragraphs = content_block.css(".article__text")
        for paragraph in paragraphs:
            if len(paragraph.text()) > 0:
                article_text += re.sub(r"\s+|\xa0|\n|\u200b", " ", paragraph.text())

        # Откидывается первое предложение текста, тк оно несодержательное
        return article_text.split(".", maxsplit=1)[1].strip()


# Класс, выполняющий функцию записи данных в csv файл
class CSVWriter:
    def __init__(self, filename: str, fieldnames: list[str]) -> None:
        self.filename = filename
        self.fieldnames = fieldnames

    def write_data(self, data: list[str]) -> None:
        with open(self.filename, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writeheader()
            for row in data:
                writer.writerow(row)


async def main():
    url_collector = UrlsCollector(RIA_URL, TARGET_ARTICLE)
    urls = url_collector.collect_urls()
    print("RIA: Сбор URL завершён")

    data_parser = DataParser()
    parsed_data = await data_parser.parse_data(urls)

    csv_writer = CSVWriter(
        TEST_FILENAME,
        fieldnames=CSV_HEADERS,
    )
    csv_writer.write_data(parsed_data)

    await data_parser.close_session()
