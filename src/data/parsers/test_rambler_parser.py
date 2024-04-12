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


CSV_HEADERS = ["Заголовок", "Компания", "Дата публикации", "Текст"]
RAMBLER_URL = "https://finance.rambler.ru/organization/sberbank-rossii/"
TARGET_ARTICLE = "Доходы России от госкомпаний резко упали"
TEST_FILENAME = "rambler_test.csv"


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
        try:
            while not scroll_complete:
                self._scroll_to_bottom(driver)
                self._wait_for_load()
                self._scroll_to_top(driver)
                try:
                    target_article = WebDriverWait(driver, 1).until(
                        EC.text_to_be_present_in_element(
                            (By.CSS_SELECTOR, "body"), TARGET_ARTICLE
                        )
                    )
                    scroll_complete = True
                except TimeoutException:
                    continue

                if target_article:
                    links = driver.find_elements(By.CSS_SELECTOR, "a._1uRkW")

                    for link in links:
                        href = link.get_attribute("href")
                        urls.append(href)
                    break

        except KeyboardInterrupt:
            pass
        finally:
            self.driver_manager.stop_driver()

        return urls

    def _scroll_to_top(self, driver: WebDriver) -> None:
        driver.execute_script("window.scrollTo(0, -1);")

    def _scroll_to_bottom(self, driver: WebDriver) -> None:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

    def _wait_for_load(self) -> None:
        time.sleep(2)


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
        title_element = html.css_first("h1#headline")

        if title_element:
            return title_element.text().replace("\xa0", " ")

        return ""

    def _parse_date(self, html: HTMLParser) -> str:
        date_element = html.css_first("time")

        if date_element:
            parsed_date = date_element.attributes.get("datetime")
            datetime_obj = datetime.fromisoformat(parsed_date)

            return datetime_obj.strftime("%d/%m/%Y")

        return ""

    def _parse_text(self, html: HTMLParser) -> str:
        content_block = html.css_first("._2mfTS")
        article_text = ""

        paragraphs = content_block.css("p")
        for paragraph in paragraphs:
            if len(paragraph.text()) > 0:
                article_text += re.sub(
                    r"\s+|\xa0|\n|\u200b", " ", paragraph.text().strip()
                )

        return article_text


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
    url_collector = UrlsCollector(RAMBLER_URL, TARGET_ARTICLE)
    urls = url_collector.collect_urls()
    print("RAMBLER: Сбор URL завершён")

    data_parser = DataParser()
    parsed_data = await data_parser.parse_data(urls)

    csv_writer = CSVWriter(
        TEST_FILENAME,
        fieldnames=CSV_HEADERS,
    )
    csv_writer.write_data(parsed_data)

    await data_parser.close_session()
