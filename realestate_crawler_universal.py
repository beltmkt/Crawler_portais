import asyncio
import logging
import re
from urllib.parse import urljoin, urlparse
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from xml.etree.ElementTree import Element, SubElement, ElementTree

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("crawler")


class RealEstateCrawler:

    def __init__(self, start_url):

        if not start_url.startswith("http"):
            start_url = "https://" + start_url

        self.start_url = start_url
        self.domain = urlparse(start_url).netloc

        self.property_links = set()
        self.properties = []

        self.visited_pages = set()
        self.pages_to_visit = [start_url]

        self.output = Path("output")
        self.output.mkdir(exist_ok=True)

    # ---------------- SCROLL ----------------

    async def auto_scroll(self, page):

        previous_height = None

        while True:

            current_height = await page.evaluate("document.body.scrollHeight")

            if previous_height == current_height:
                break

            previous_height = current_height

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)

    # ---------------- EXTRAIR LINKS ----------------

    def extract_links(self, html, base):

        soup = BeautifulSoup(html, "html.parser")

        pages = []
        props = []

        for a in soup.find_all("a", href=True):

            link = urljoin(base, a["href"])

            if self.domain not in link:
                continue

            # detectar anúncio
            if "/imovel/" in link.lower():
                props.append(link)

            # detectar paginação
            if any(x in link.lower() for x in [
                "/page/",
                "paged=",
                "page="
            ]):
                pages.append(link)

        return pages, props

    # ---------------- CRAWL LISTAGENS ----------------

    async def crawl_listings(self, context):

        page = await context.new_page()

        while self.pages_to_visit:

            url = self.pages_to_visit.pop(0)

            if url in self.visited_pages:
                continue

            self.visited_pages.add(url)

            log.info(f"Acessando listagem {url}")

            try:

                await page.goto(url, timeout=60000)
                await page.wait_for_load_state("networkidle")

                await self.auto_scroll(page)

            except:
                continue

            html = await page.content()

            pages, props = self.extract_links(html, url)

            for p in pages:

                if p not in self.visited_pages:
                    self.pages_to_visit.append(p)

            for p in props:
                self.property_links.add(p)

        await page.close()

        log.info(f"Total anúncios detectados: {len(self.property_links)}")

    # ---------------- EXTRAIR DADOS ----------------

    def parse_property(self, html, url):

        soup = BeautifulSoup(html, "html.parser")

        text = soup.get_text(" ")

        data = {}

        data["url"] = url

        title = soup.find("h1")
        data["title"] = title.get_text(strip=True) if title else ""

        desc = soup.find("p")
        data["description"] = desc.get_text(strip=True) if desc else ""

        price = re.search(r'R\$\s?[\d\.,]+', text)
        data["price"] = price.group() if price else ""

        area = re.search(r'(\d+)\s?m²', text)
        data["area"] = area.group(1) if area else ""

        rooms = re.search(r'(\d+)\s?quartos?', text, re.I)
        data["rooms"] = rooms.group(1) if rooms else ""

        baths = re.search(r'(\d+)\s?banheiros?', text, re.I)
        data["bathrooms"] = baths.group(1) if baths else ""

        images = []

        for img in soup.find_all("img"):

            src = img.get("src")

            if not src:
                continue

            if any(x in src.lower() for x in ["jpg","jpeg","png","webp"]):
                images.append(src)

        data["images"] = images

        return data

    # ---------------- CRAWL ANÚNCIOS ----------------

    async def crawl_properties(self, context):

        sem = asyncio.Semaphore(5)

        async def worker(url):

            async with sem:

                page = await context.new_page()

                try:

                    log.info(f"Abrindo anúncio {url}")

                    await page.goto(url, timeout=60000)
                    await page.wait_for_load_state("networkidle")

                    html = await page.content()

                    prop = self.parse_property(html, url)

                    self.properties.append(prop)

                except:

                    log.warning(f"Erro ao abrir {url}")

                await page.close()

        tasks = [worker(url) for url in self.property_links]

        await asyncio.gather(*tasks)

    # ---------------- XML ----------------

    def generate_xml(self):

        root = Element("Carga")
        imoveis = SubElement(root, "Imoveis")

        for i, p in enumerate(self.properties):

            imovel = SubElement(imoveis, "Imovel")

            SubElement(imovel,"CodigoImovel").text = str(i+1)

            SubElement(imovel,"TituloImovel").text = p["title"]
            SubElement(imovel,"Observacao").text = p["description"]

            SubElement(imovel,"PrecoAluguel").text = p["price"]

            SubElement(imovel,"AreaUtil").text = p["area"]
            SubElement(imovel,"QtdBanheiros").text = p["bathrooms"]

            fotos = SubElement(imovel,"Fotos")

            for idx,img in enumerate(p["images"]):

                foto = SubElement(fotos,"Foto")

                SubElement(foto,"URLArquivo").text = img
                SubElement(foto,"Principal").text = "1" if idx == 0 else "0"

        tree = ElementTree(root)

        tree.write(
            self.output/"imoveis.xml",
            encoding="utf-8",
            xml_declaration=True
        )

        log.info("XML gerado")

    # ---------------- RUN ----------------

    async def run(self):

        async with async_playwright() as p:

            browser = await p.chromium.launch(headless=True)

            context = await browser.new_context()

            await self.crawl_listings(context)

            await self.crawl_properties(context)

            await browser.close()

        self.generate_xml()

        log.info(f"Total imóveis coletados: {len(self.properties)}")


# ---------------- MAIN ----------------

if __name__ == "__main__":

    import sys

    if len(sys.argv) < 2:

        print("Uso:")
        print("python realestate_crawler_pro.py https://site.com/imoveis")
        exit()

    url = sys.argv[1]

    crawler = RealEstateCrawler(url)

    asyncio.run(crawler.run())