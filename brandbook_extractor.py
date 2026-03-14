import asyncio
import re
import logging
from urllib.parse import urljoin, urlparse, parse_qs
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
import aiohttp
import os
import yt_dlp  # Biblioteca para baixar vídeos do YouTube

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger()


class BrandBookExtractor:

    def __init__(self, url):

        if not url.startswith("http"):
            url = "https://" + url

        self.start_url = url
        self.domain = urlparse(url).netloc

        self.visited = set()
        self.queue = [url]
        
        # Dados organizados por página
        self.page_data = {}  # url -> {logos, imagens, textos, etc}
        
        # Dados globais
        self.global_logos = set()
        self.global_favicons = set()
        self.global_icons = set()
        self.global_banners = set()
        self.global_images = set()
        self.global_videos = set()
        self.global_video_urls = set()  # URLs dos vídeos para download
        self.global_colors = []
        self.global_fonts = set()
        
        # Para identificar páginas principais
        self.main_page_patterns = []  # Será preenchido durante a análise
        self.page_hierarchy = defaultdict(list)  # Para organizar por importância
        self.page_scores = {}  # Pontuação de cada página (importância)

        self.output = Path("brandbook_output")
        self.output.mkdir(exist_ok=True)
        
        # Pastas para organizar os downloads
        self.images_dir = self.output / "images"
        self.videos_dir = self.output / "videos"
        self.images_dir.mkdir(exist_ok=True)
        self.videos_dir.mkdir(exist_ok=True)


# ---------------- URL NORMALIZER ---------------- #

    def normalize(self, url):

        if not url:
            return None

        if url.startswith("//"):
            url = "https:" + url
            
        # Remove fragmentos e parâmetros desnecessários
        parsed = urlparse(url)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        
        return clean_url


# ---------------- DOWNLOAD FILES ---------------- #

    async def download_file(self, url, filepath):
        """Download de arquivo (imagem ou vídeo)"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        with open(filepath, 'wb') as f:
                            while True:
                                chunk = await response.content.read(1024)
                                if not chunk:
                                    break
                                f.write(chunk)
                        return True
        except Exception as e:
            log.error(f"Erro ao baixar {url}: {e}")
        return False

    def download_youtube_video(self, url, output_path):
        """Baixa vídeo do YouTube usando yt-dlp"""
        try:
            ydl_opts = {
                'format': 'best[height<=720]',  # Qualidade máxima 720p para não pesar muito
                'outtmpl': str(output_path),
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                return Path(filename)
        except Exception as e:
            log.error(f"Erro ao baixar vídeo do YouTube {url}: {e}")
            return None

    def extract_youtube_id(self, url):
        """Extrai ID do YouTube de várias formas de URL"""
        patterns = [
            r'(?:youtube\.com\/watch\?v=)([^&]+)',
            r'(?:youtube\.com\/embed\/)([^"?]+)',
            r'(?:youtu\.be\/)([^"?]+)',
            r'(?:youtube\.com\/v\/)([^"?]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def get_filename_from_url(self, url):
        """Extrai nome do arquivo da URL"""
        parsed = urlparse(url)
        path = parsed.path
        filename = os.path.basename(path)
        
        # Se for YouTube, usa o ID
        youtube_id = self.extract_youtube_id(url)
        if youtube_id:
            return f"youtube_{youtube_id}.mp4"
        
        # Se não tiver extensão, adiciona .mp4 para vídeos
        if not filename or '.' not in filename:
            if 'video' in url or 'youtube' in url or 'vimeo' in url:
                filename = f"video_{hash(url) % 10000}.mp4"
            else:
                filename = f"image_{hash(url) % 10000}.jpg"
        
        # Remove caracteres especiais
        filename = re.sub(r'[^\w\-_\. ]', '_', filename)
        return filename


# ---------------- ANALISAR ESTRUTURA DO SITE ---------------- #

    def analyze_site_structure(self, soup, base_url):
        """Analisa a estrutura do site para identificar páginas principais"""
        
        links = []
        link_texts = []
        link_importance = {}
        
        # Coleta todos os links do menu/navegação principal
        nav_elements = soup.find_all(['nav', 'header']) + soup.find_all(class_=re.compile(r'menu|navbar|navigation|nav|header', re.I))
        
        for nav in nav_elements:
            for a in nav.find_all('a', href=True):
                href = a.get('href')
                if not href or href.startswith('#') or href.startswith('javascript:'):
                    continue
                    
                full_url = urljoin(base_url, href)
                if self.domain not in full_url:
                    continue
                    
                text = a.get_text(strip=True)
                if text and len(text) < 50:  # Texto de menu geralmente é curto
                    link_texts.append(text.lower())
                    
                # Calcula importância baseada na posição
                importance = 10  # Alta importância para links do menu
                link_importance[full_url] = max(link_importance.get(full_url, 0), importance)
                
                parsed = urlparse(full_url)
                path_parts = parsed.path.strip('/').split('/')
                
                # Links com path curto são provavelmente páginas principais
                if len(path_parts) == 1 and path_parts[0]:
                    link_importance[full_url] = max(link_importance.get(full_url, 0), 8)
                
                links.append(full_url)
        
        # Também analisa links do corpo da página (podem ser importantes)
        for a in soup.find_all('a', href=True):
            href = a.get('href')
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
                
            full_url = urljoin(base_url, href)
            if self.domain not in full_url or full_url in links:
                continue
                
            # Verifica se é um link importante (botões, CTAs, etc)
            classes = ' '.join(a.get('class', [])).lower()
            if any(word in classes for word in ['btn', 'button', 'cta', 'more', 'saiba']):
                link_importance[full_url] = max(link_importance.get(full_url, 0), 7)
                links.append(full_url)
        
        # Identifica padrões comuns nos textos dos links
        if link_texts:
            word_freq = Counter()
            for text in link_texts:
                words = re.findall(r'\b\w+\b', text)
                word_freq.update(words)
            
            # Palavras mais comuns nos menus (provavelmente seções principais)
            common_words = [word for word, count in word_freq.most_common(10) 
                          if len(word) > 2 and count > 1]
            
            self.main_page_patterns = common_words
            log.info(f"Padrões identificados no menu: {common_words}")
        
        return links, link_importance


# ---------------- EXTRACT LINKS ---------------- #

    def extract_links(self, soup, base):

        links = set()
        link_importance = {}

        # Primeiro, analisa a estrutura do site
        nav_links, nav_importance = self.analyze_site_structure(soup, base)
        for link in nav_links:
            links.add(link)
            if link in nav_importance:
                link_importance[link] = nav_importance[link]

        # Também coleta outros links que podem ser relevantes
        for a in soup.find_all("a", href=True):
            link = urljoin(base, a["href"])
            
            if self.domain not in link:
                continue
                
            link = self.normalize(link)
            
            # Evita links duplicados ou muito longos
            parsed = urlparse(link)
            path_depth = len([p for p in parsed.path.split('/') if p])
            
            # Links com profundidade <= 2 são provavelmente páginas principais
            if path_depth <= 2:
                links.add(link)
                if link not in link_importance:
                    link_importance[link] = 5  # Importância média

        return list(links), link_importance


# ---------------- CALCULAR IMPORTÂNCIA DA PÁGINA ---------------- #

    def calculate_page_importance(self, url, soup, link_importance):
        """Calcula a importância de uma página baseado em vários fatores"""
        
        score = 0
        
        # Importância baseada nos links que apontam para ela
        score += link_importance.get(url, 0)
        
        # Verifica se é a home page
        if url == self.start_url or url.rstrip('/') == self.start_url.rstrip('/'):
            score += 100  # Home é sempre a mais importante
        
        # Analisa o conteúdo da página
        title = soup.find('title')
        if title:
            title_text = title.string.lower() if title.string else ''
            # Palavras que indicam página principal
            main_indicators = ['home', 'início', 'principal', 'inicio']
            if any(ind in title_text for ind in main_indicators):
                score += 15
        
        # Verifica headers
        h1 = soup.find('h1')
        if h1:
            h1_text = h1.get_text().lower()
            if any(word in h1_text for word in ['home', 'início', 'welcome']):
                score += 10
        
        # Quantidade de conteúdo (páginas principais têm mais conteúdo)
        text_length = len(soup.get_text())
        if text_length > 500:
            score += min(text_length / 1000, 20)  # Max 20 pontos
        
        # Presença de elementos importantes
        if soup.find('nav'):
            score += 5
        if soup.find('header'):
            score += 3
        if soup.find('footer'):
            score += 3
        
        # URLs com path curto são mais importantes
        parsed = urlparse(url)
        path_depth = len([p for p in parsed.path.split('/') if p])
        if path_depth == 0:  # Home
            score += 50
        elif path_depth == 1:  # /sobre, /contato, etc
            score += 30
        elif path_depth == 2:  # /categoria/produto
            score += 15
        
        return score


# ---------------- EXTRAIR DADOS DA PÁGINA ---------------- #

    def extract_page_data(self, soup, url):
        """Extrai todos os dados de uma página específica"""
        
        # Extrai título da página
        title_tag = soup.find('title')
        page_title = title_tag.string if title_tag else 'Sem título'
        
        page_info = {
            'url': url,
            'title': page_title.strip() if page_title else 'Sem título',
            'importance': 0,
            'logos': set(),
            'favicons': set(),
            'icons': set(),
            'banners': set(),
            'images': set(),
            'videos': set(),
            'video_files': [],  # Arquivos de vídeo baixados localmente
            'headings': [],  # h1, h2, h3, h4
            'paragraphs': [],  # textos principais
            'buttons': [],  # textos de botões
            'menu_items': [],  # itens de menu
            'footer_texts': [],  # textos do rodapé
            'links': [],  # links importantes da página
            'colors': [],
            'fonts': set(),
            'meta_description': '',
            'meta_keywords': '',
            'has_form': False,
            'has_contact_info': False
        }
        
        # Meta tags
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            page_info['meta_description'] = meta_desc['content']
            
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            page_info['meta_keywords'] = meta_keywords['content']

        # Verifica se tem formulário de contato
        if soup.find('form'):
            page_info['has_form'] = True
            
        # Verifica informações de contato
        contact_patterns = re.compile(r'contato|telefone|phone|email|endereço|address|whatsapp', re.I)
        if soup.find(string=contact_patterns):
            page_info['has_contact_info'] = True

        # imagens
        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue

            src = self.normalize(urljoin(url, src))
            alt = (img.get("alt") or "").lower()
            classes = " ".join(img.get("class", [])).lower()
            id_elem = (img.get("id") or "").lower()

            # Identifica tipo de imagem baseado em atributos
            img_text = f"{alt} {classes} {id_elem}"
            
            if "logo" in img_text or "logo" in src.lower():
                page_info['logos'].add(src)
                self.global_logos.add(src)

            elif any(word in img_text for word in ['banner', 'hero', 'slide', 'carousel', 'destaque']):
                page_info['banners'].add(src)
                self.global_banners.add(src)

            elif any(word in img_text for word in ['icon', 'ico', 'favicon']):
                page_info['icons'].add(src)
                self.global_icons.add(src)

            else:
                # Filtra imagens relevantes (não muito pequenas)
                width = img.get('width')
                height = img.get('height')
                if width and height:
                    try:
                        if int(width) > 100 and int(height) > 100:
                            page_info['images'].add(src)
                            self.global_images.add(src)
                    except:
                        page_info['images'].add(src)
                        self.global_images.add(src)
                else:
                    # Se não tem dimensões, assume que é relevante
                    page_info['images'].add(src)
                    self.global_images.add(src)

        # favicon
        for link in soup.find_all("link", rel=True):
            rel = " ".join(link.get("rel")).lower()
            if "icon" in rel:
                href = link.get("href")
                if href:
                    favicon = self.normalize(urljoin(url, href))
                    page_info['favicons'].add(favicon)
                    self.global_favicons.add(favicon)

        # vídeos (arquivos de vídeo)
        for video in soup.find_all("video"):
            # Pega a fonte principal
            src = video.get("src")
            if src:
                video_url = self.normalize(urljoin(url, src))
                page_info['videos'].add(video_url)
                self.global_videos.add(video_url)
                self.global_video_urls.add(video_url)
            
            # Pega sources dentro da tag video
            for source in video.find_all("source"):
                src = source.get("src")
                if src:
                    video_url = self.normalize(urljoin(url, src))
                    page_info['videos'].add(video_url)
                    self.global_videos.add(video_url)
                    self.global_video_urls.add(video_url)

        # vídeos incorporados (YouTube, Vimeo) em iframes
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src")
            if src:
                # Tenta extrair ID do YouTube
                youtube_match = re.search(r'(?:youtube\.com/embed/|youtu\.be/)([^"?]+)', src)
                if youtube_match:
                    video_id = youtube_match.group(1)
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    page_info['videos'].add(video_url)
                    self.global_videos.add(video_url)
                    self.global_video_urls.add(video_url)
                    log.info(f"✅ Vídeo YouTube encontrado em iframe: {video_url}")
                
                vimeo_match = re.search(r'player\.vimeo\.com/video/(\d+)', src)
                if vimeo_match:
                    video_id = vimeo_match.group(1)
                    video_url = f"https://vimeo.com/{video_id}"
                    page_info['videos'].add(video_url)
                    self.global_videos.add(video_url)
                    self.global_video_urls.add(video_url)

        # Vídeos em scripts/players customizados (como o vídeo de capa)
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                # Procura por IDs de YouTube em scripts
                youtube_pattern = r'(?:youtube\.com/embed/|youtu\.be/|videoId:\s*["\'])([a-zA-Z0-9_-]{11})'
                matches = re.findall(youtube_pattern, script.string)
                for video_id in matches:
                    if len(video_id) == 11:  # IDs do YouTube têm 11 caracteres
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        page_info['videos'].add(video_url)
                        self.global_videos.add(video_url)
                        self.global_video_urls.add(video_url)
                        log.info(f"✅ Vídeo YouTube encontrado em script: {video_url}")

        # fontes
        for link in soup.find_all("link", href=True):
            if "fonts.googleapis" in link["href"]:
                match = re.search(r'family=([^&]+)', link["href"])
                if match:
                    fams = match.group(1).split("|")
                    for f in fams:
                        font_name = f.split(":")[0].replace("+", " ")
                        page_info['fonts'].add(font_name)
                        self.global_fonts.add(font_name)

        # cores
        css = ""
        for style in soup.find_all("style"):
            if style.string:
                css += style.string
                
        # Cores inline
        for tag in soup.find_all(style=True):
            style = tag.get('style', '')
            colors_inline = re.findall(r'#[0-9a-fA-F]{6}', style)
            page_info['colors'].extend(colors_inline)
            self.global_colors.extend(colors_inline)

        colors = re.findall(r'#[0-9a-fA-F]{6}', css)
        page_info['colors'].extend(colors)
        self.global_colors.extend(colors)
        
        # Extrair textos
        self.extract_texts(soup, page_info)
        
        return page_info
    
    def extract_texts(self, soup, page_info):
        """Extrai textos de uma página e armazena no page_info"""
        
        # Headings (títulos)
        for h in soup.find_all(['h1', 'h2', 'h3', 'h4']):
            text = h.get_text(strip=True)
            if text and len(text) > 3:
                page_info['headings'].append({
                    'tag': h.name,
                    'text': text,
                    'class': h.get('class', [])
                })

        # Parágrafos principais (ignora textos muito curtos)
        for p in soup.find_all('p'):
            text = p.get_text(strip=True)
            if text and len(text) > 30:  # Aumentado para pegar apenas parágrafos relevantes
                # Evita duplicatas próximas
                if not any(self.is_similar_text(text, existing) for existing in page_info['paragraphs'][-5:]):
                    page_info['paragraphs'].append(text)

        # Botões
        button_selectors = [
            ('button', None),
            ('a', re.compile(r'btn|button|botao|cta', re.I)),
            ('input', {'type': 'submit'}),
            ('input', {'type': 'button'}),
            ('*', re.compile(r'btn|button|botao|cta', re.I))
        ]
        
        for tag, class_pattern in button_selectors:
            if class_pattern and isinstance(class_pattern, re.Pattern):
                elements = soup.find_all(tag, class_=class_pattern)
            elif class_pattern and isinstance(class_pattern, dict):
                elements = soup.find_all(tag, attrs=class_pattern)
            else:
                elements = soup.find_all(tag)
            
            for btn in elements:
                text = btn.get_text(strip=True)
                if text and len(text) < 100 and text not in page_info['buttons']:
                    page_info['buttons'].append(text)

        # Menu items (navegação principal)
        nav_elements = soup.find_all(['nav', 'header']) + soup.find_all(class_=re.compile(r'menu|navbar|navigation', re.I))
        
        for nav in nav_elements:
            for a in nav.find_all('a'):
                text = a.get_text(strip=True)
                if text and len(text) < 50 and text not in page_info['menu_items']:
                    href = a.get('href', '')
                    if href and not href.startswith('#') and not href.startswith('javascript:'):
                        page_info['menu_items'].append({
                            'text': text,
                            'url': urljoin(page_info['url'], href)
                        })

        # Footer texts
        footer = soup.find('footer')
        if footer:
            footer_text = footer.get_text(strip=True)
            if footer_text:
                # Divide em linhas e pega as relevantes
                lines = [line.strip() for line in footer_text.split('\n') if line.strip()]
                page_info['footer_texts'].extend(lines[:10])  # Limita a 10 linhas
            
            # Links importantes do footer
            for a in footer.find_all('a'):
                text = a.get_text(strip=True)
                href = a.get('href', '')
                if text and href and not href.startswith('#'):
                    page_info['footer_texts'].append(f"{text}: {href}")
        
        # Remove duplicatas mantendo ordem
        page_info['footer_texts'] = list(dict.fromkeys(page_info['footer_texts']))
        page_info['buttons'] = list(dict.fromkeys(page_info['buttons']))
    
    def is_similar_text(self, text1, text2, threshold=0.8):
        """Verifica se dois textos são similares (para evitar duplicatas)"""
        if not text1 or not text2:
            return False
        return SequenceMatcher(None, text1.lower(), text2.lower()).ratio() > threshold


# ---------------- CRAWL ---------------- #

    async def crawl(self):

        async with async_playwright() as p:

            browser = await p.chromium.launch(headless=True)

            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )

            page_count = 0
            max_pages = 30  # Limite para não sobrecarregar
            
            # Primeiro, analisa a home para entender a estrutura
            log.info("Analisando home page para entender estrutura do site...")
            
            first_page = await context.new_page()
            try:
                await first_page.goto(self.start_url, timeout=60000, wait_until='networkidle')
                await asyncio.sleep(3)
                html = await first_page.content()
                soup = BeautifulSoup(html, "html.parser")
                
                # Analisa estrutura e encontra links importantes
                important_links, link_importance = self.extract_links(soup, self.start_url)
                
                # Adiciona links importantes à fila
                for link in important_links:
                    if link not in self.visited and link not in self.queue:
                        self.queue.append(link)
                        self.page_scores[link] = link_importance.get(link, 5)
                
                await first_page.close()
                
            except Exception as e:
                log.error(f"Erro ao analisar home: {e}")

            # Processa a fila de páginas
            while self.queue and page_count < max_pages:

                url = self.queue.pop(0)

                if url in self.visited:
                    continue

                self.visited.add(url)
                page_count += 1

                log.info(f"[Página {page_count}] Analisando {url}")

                page = await context.new_page()

                try:
                    await page.goto(url, timeout=60000, wait_until='networkidle')
                    await asyncio.sleep(2)
                    html = await page.content()

                except Exception as e:
                    log.error(f"Erro ao acessar {url}: {e}")
                    await page.close()
                    continue

                soup = BeautifulSoup(html, "html.parser")

                # Extrai dados desta página
                page_data = self.extract_page_data(soup, url)
                
                # Calcula importância da página
                importance = self.calculate_page_importance(url, soup, self.page_scores)
                page_data['importance'] = importance
                
                self.page_data[url] = page_data

                # Encontra mais links importantes
                new_links, link_importance = self.extract_links(soup, url)
                
                for link in new_links:
                    if link not in self.visited and link not in self.queue:
                        # Adiciona à fila com sua importância
                        self.queue.append(link)
                        self.page_scores[link] = link_importance.get(link, 5)

                await page.close()
                
                # Pequena pausa entre requisições
                await asyncio.sleep(1)

            await browser.close()
            
            # Ordena páginas por importância para o relatório
            self.page_data = dict(sorted(
                self.page_data.items(), 
                key=lambda x: x[1]['importance'], 
                reverse=True
            ))


# ---------------- DOWNLOAD ALL FILES ---------------- #

    async def download_all_files(self):
        """Baixa todas as imagens e vídeos encontrados"""
        log.info("📥 Iniciando download de arquivos...")
        
        # Dicionário para mapear URLs para arquivos locais
        url_to_local = {}
        
        # Baixa imagens (logos, banners, icons, images)
        all_images = (self.global_logos | self.global_banners | 
                     self.global_icons | self.global_images)
        
        log.info(f"Baixando {len(all_images)} imagens...")
        for i, img_url in enumerate(all_images, 1):
            if i % 10 == 0:
                log.info(f"  Progresso imagens: {i}/{len(all_images)}")
            
            filename = self.get_filename_from_url(img_url)
            filepath = self.images_dir / filename
            
            # Evita sobrescrever
            counter = 1
            while filepath.exists():
                name, ext = os.path.splitext(filename)
                filepath = self.images_dir / f"{name}_{counter}{ext}"
                counter += 1
            
            success = await self.download_file(img_url, filepath)
            if success:
                url_to_local[img_url] = str(filepath.relative_to(self.output))
        
        # Baixa vídeos
        log.info(f"Baixando {len(self.global_video_urls)} vídeos...")
        for i, video_url in enumerate(self.global_video_urls, 1):
            log.info(f"  Baixando vídeo {i}/{len(self.global_video_urls)}: {video_url}")
            
            filename = self.get_filename_from_url(video_url)
            filepath = self.videos_dir / filename
            
            # Evita sobrescrever
            counter = 1
            while filepath.exists():
                name, ext = os.path.splitext(filename)
                filepath = self.videos_dir / f"{name}_{counter}{ext}"
                counter += 1
            
            # Verifica se é YouTube
            youtube_id = self.extract_youtube_id(video_url)
            if youtube_id:
                log.info(f"    📺 Baixando vídeo do YouTube (ID: {youtube_id})...")
                downloaded_file = await asyncio.to_thread(self.download_youtube_video, video_url, filepath.with_suffix(''))
                if downloaded_file:
                    url_to_local[video_url] = str(downloaded_file.relative_to(self.output))
                    
                    # Associa o arquivo baixado à página correspondente
                    for page_data in self.page_data.values():
                        if video_url in page_data['videos']:
                            page_data['video_files'].append({
                                'url': video_url,
                                'local': str(downloaded_file.relative_to(self.output)),
                                'youtube_id': youtube_id
                            })
            else:
                # Vídeo normal
                success = await self.download_file(video_url, filepath)
                if success:
                    url_to_local[video_url] = str(filepath.relative_to(self.output))
                    
                    # Associa o arquivo baixado à página correspondente
                    for page_data in self.page_data.values():
                        if video_url in page_data['videos']:
                            page_data['video_files'].append({
                                'url': video_url,
                                'local': str(filepath.relative_to(self.output))
                            })
        
        log.info("✅ Download de arquivos concluído!")
        return url_to_local


# ---------------- GENERATE BRANDBOOK ---------------- #

    def generate_brandbook(self):

        palette = [c for c,_ in Counter(self.global_colors).most_common(12)]
        
        # Estatísticas gerais
        total_images = (len(self.global_logos) + len(self.global_banners) + 
                       len(self.global_icons) + len(self.global_images))
        
        html = f"""
        <html>
        <head>
        <title>Brandbook {self.domain}</title>
        <meta charset="UTF-8">
        <style>
            * {{ 
                box-sizing: border-box; 
                margin: 0;
                padding: 0;
            }}
            body {{ 
                font-family: 'Segoe UI', Arial, sans-serif; 
                margin: 0; 
                padding: 20px; 
                background: #f5f5f5;
                color: #333;
            }}
            .container {{ 
                max-width: 1400px; 
                margin: 0 auto;
                width: 100%;
            }}
            h1 {{ 
                color: #2c3e50; 
                border-bottom: 4px solid #3498db; 
                padding-bottom: 15px;
                margin: 0 0 20px 0;
                font-size: 28px;
            }}
            h2 {{ 
                color: #34495e; 
                border-bottom: 2px solid #bdc3c7; 
                padding-bottom: 8px; 
                margin: 25px 0 15px 0;
                font-size: 24px;
            }}
            h3 {{ 
                color: #7f8c8d; 
                margin: 20px 0 10px 0;
                font-size: 20px;
            }}
            h4 {{
                font-size: 18px;
                margin: 15px 0 10px 0;
            }}
            h5 {{
                font-size: 16px;
                margin: 12px 0 8px 0;
                color: #555;
            }}
            
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 15px;
                margin: 20px 0;
            }}
            .stat-card {{
                background: white;
                padding: 15px;
                border-radius: 10px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                text-align: center;
                border-top: 4px solid #3498db;
            }}
            .stat-number {{
                font-size: 28px;
                font-weight: bold;
                color: #2c3e50;
                display: block;
            }}
            .stat-label {{
                color: #7f8c8d;
                font-size: 13px;
                text-transform: uppercase;
            }}
            
            .page-card {{
                background: white;
                margin: 25px 0;
                border-radius: 12px;
                box-shadow: 0 3px 10px rgba(0,0,0,0.1);
                overflow: hidden;
                width: 100%;
            }}
            .page-header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 15px 20px;
                cursor: pointer;
                user-select: none;
            }}
            .page-header:hover {{
                opacity: 0.95;
            }}
            .page-header h3 {{
                margin: 0 0 5px 0;
                color: white;
                font-size: 20px;
            }}
            .page-header small {{
                opacity: 0.9;
                font-size: 13px;
                display: block;
                margin-bottom: 8px;
            }}
            .importance-badge {{
                background: #ffd700;
                color: #2c3e50;
                padding: 4px 10px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: bold;
                display: inline-block;
                margin-right: 8px;
            }}
            
            .page-content {{
                padding: 20px;
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                max-height: 600px;
                overflow-y: auto;
            }}
            
            @media (max-width: 768px) {{
                .page-content {{
                    grid-template-columns: 1fr;
                }}
            }}
            
            .visual-section, .text-section {{
                background: #f8f9fa;
                padding: 15px;
                border-radius: 10px;
                overflow: hidden;
            }}
            
            .image-gallery {{
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                margin: 8px 0;
                max-height: 200px;
                overflow-y: auto;
                padding: 5px;
                border: 1px solid #eee;
                border-radius: 5px;
                background: white;
            }}
            .image-gallery img {{
                border: 1px solid #ddd;
                padding: 2px;
                background: white;
                max-width: 100px;
                max-height: 100px;
                object-fit: contain;
                border-radius: 4px;
                transition: transform 0.2s;
                cursor: pointer;
            }}
            .image-gallery img:hover {{
                transform: scale(1.1);
                box-shadow: 0 3px 10px rgba(0,0,0,0.2);
                z-index: 10;
            }}
            
            .gallery-expand {{
                background: #3498db;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 5px;
                cursor: pointer;
                font-size: 12px;
                margin: 5px 0;
            }}
            .gallery-expand:hover {{
                background: #2980b9;
            }}
            
            .full-gallery-modal {{
                display: none;
                position: fixed;
                z-index: 1000;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(0,0,0,0.9);
                overflow: auto;
            }}
            .full-gallery-content {{
                position: relative;
                margin: 50px auto;
                padding: 20px;
                width: 90%;
                max-width: 1200px;
                background: white;
                border-radius: 10px;
            }}
            .close-modal {{
                position: absolute;
                right: 25px;
                top: 10px;
                color: #333;
                font-size: 35px;
                font-weight: bold;
                cursor: pointer;
            }}
            .close-modal:hover {{
                color: #f00;
            }}
            .full-gallery-grid {{
                display: flex;
                flex-wrap: wrap;
                gap: 15px;
                margin-top: 30px;
                max-height: 70vh;
                overflow-y: auto;
                padding: 10px;
            }}
            .full-gallery-grid img {{
                max-width: 200px;
                max-height: 200px;
                object-fit: contain;
                border: 2px solid #ddd;
                padding: 5px;
                background: white;
                border-radius: 5px;
            }}
            
            .color-palette {{
                display: flex;
                flex-wrap: wrap;
                gap: 5px;
                margin: 10px 0;
                max-height: 100px;
                overflow-y: auto;
                padding: 5px;
                background: white;
                border-radius: 5px;
            }}
            .color-box {{
                width: 40px;
                height: 40px;
                border-radius: 6px;
                border: 2px solid white;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                cursor: pointer;
                transition: transform 0.2s;
                flex-shrink: 0;
            }}
            .color-box:hover {{
                transform: scale(1.15);
                box-shadow: 0 4px 8px rgba(0,0,0,0.2);
                z-index: 10;
            }}
            
            .text-item {{
                background: white;
                padding: 10px 12px;
                margin: 6px 0;
                border-radius: 6px;
                border-left: 4px solid #3498db;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                font-size: 14px;
                max-height: 80px;
                overflow-y: auto;
            }}
            .heading-item {{ border-left-color: #9b59b6; }}
            .button-item {{ border-left-color: #2ecc71; }}
            
            .meta-info {{
                background: #e8f4f8;
                padding: 12px;
                border-radius: 6px;
                margin: 10px 0;
                font-size: 13px;
                max-height: 150px;
                overflow-y: auto;
            }}
            
            .footer {{
                text-align: center;
                margin-top: 40px;
                padding: 20px;
                color: #7f8c8d;
                border-top: 2px solid #bdc3c7;
                font-size: 13px;
            }}
            
            .toc {{
                background: white;
                padding: 15px;
                border-radius: 10px;
                margin: 20px 0;
                border: 1px solid #ddd;
                max-height: 400px;
                overflow-y: auto;
            }}
            .toc-header {{
                background: #f0f0f0;
                padding: 10px 15px;
                margin: -15px -15px 15px -15px;
                border-radius: 10px 10px 0 0;
                border-bottom: 2px solid #3498db;
                cursor: pointer;
                user-select: none;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .toc-header:hover {{
                background: #e0e0e0;
            }}
            .toc-header h4 {{
                margin: 0;
                color: #2c3e50;
            }}
            .toc-arrow {{
                font-size: 20px;
                transition: transform 0.3s;
            }}
            .toc-content {{
                transition: max-height 0.3s ease-out;
                overflow: hidden;
            }}
            .toc-content.collapsed {{
                max-height: 0;
                padding: 0;
                margin: 0;
            }}
            .toc-content.expanded {{
                max-height: 300px;
                overflow-y: auto;
            }}
            .toc a {{
                color: #3498db;
                text-decoration: none;
                display: block;
                padding: 6px 10px;
                border-bottom: 1px solid #eee;
                font-size: 14px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }}
            .toc a:hover {{
                background: #f0f7ff;
            }}
            
            .badge {{
                display: inline-block;
                padding: 2px 6px;
                border-radius: 10px;
                font-size: 10px;
                font-weight: bold;
                margin-left: 5px;
            }}
            .badge-home {{ background: #27ae60; color: white; }}
            .badge-important {{ background: #f39c12; color: white; }}
            .badge-youtube {{ background: #ff0000; color: white; }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 14px;
                background: white;
                border-radius: 5px;
                overflow: hidden;
            }}
            th, td {{
                padding: 8px 10px;
                text-align: left;
                border-bottom: 1px solid #eee;
            }}
            th {{
                background: #34495e;
                color: white;
            }}
            
            hr {{
                margin: 15px 0;
                border: none;
                border-top: 1px solid #ddd;
            }}
            
            .video-container {{
                max-height: 300px;
                overflow-y: auto;
                padding: 5px;
                background: white;
                border-radius: 5px;
            }}
            .video-item {{
                display: block;
                padding: 8px;
                margin: 5px 0;
                background: #f0f0f0;
                border-radius: 5px;
                font-size: 12px;
                border-left: 4px solid #e74c3c;
            }}
            .video-item a {{
                color: #3498db;
                text-decoration: none;
            }}
            .video-item a:hover {{
                text-decoration: underline;
            }}
            .video-local {{
                display: block;
                font-size: 11px;
                color: #27ae60;
                margin-top: 3px;
            }}
            video {{
                max-width: 100%;
                max-height: 150px;
                margin: 5px 0;
            }}
        </style>
        </head>

        <body>
            <div class="container">
                <h1>📘 Brandbook - {self.domain}</h1>
                <p><strong>Data de extração:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
                <p><strong>Padrões identificados no menu:</strong> {', '.join(self.main_page_patterns) or 'Nenhum padrão específico'}</p>
                
                <!-- Stats Cards -->
                <div class="stats-grid">
                    <div class="stat-card">
                        <span class="stat-number">{len(self.page_data)}</span>
                        <span class="stat-label">Páginas</span>
                    </div>
                    <div class="stat-card">
                        <span class="stat-number">{total_images}</span>
                        <span class="stat-label">Imagens</span>
                    </div>
                    <div class="stat-card">
                        <span class="stat-number">{len(self.global_videos)}</span>
                        <span class="stat-label">Vídeos</span>
                    </div>
                    <div class="stat-card">
                        <span class="stat-number">{len(palette)}</span>
                        <span class="stat-label">Cores</span>
                    </div>
                    <div class="stat-card">
                        <span class="stat-number">{len(self.global_fonts)}</span>
                        <span class="stat-label">Fontes</span>
                    </div>
                </div>
                
                <!-- Ranking de Páginas (Agora como dropdown) -->
                <div class="toc" id="ranking-section">
                    <div class="toc-header" onclick="toggleRanking()">
                        <h4>📊 RANKING DE PÁGINAS POR IMPORTÂNCIA</h4>
                        <span class="toc-arrow" id="ranking-arrow">▼</span>
                    </div>
                    <div id="ranking-content" class="toc-content expanded">
                        {self.generate_toc()}
                    </div>
                </div>
                
                <!-- Visão Geral -->
                <div class="page-card">
                    <div class="page-header" onclick="toggleSection('global-section')">
                        <h3>📊 VISÃO GERAL - TODAS AS PÁGINAS</h3>
                        <small>Clique para expandir/recolher</small>
                    </div>
                    <div id="global-section" class="page-content" style="display: grid;">
                        <div class="visual-section">
                            <h4>🎨 Identidade Visual Global</h4>
                            
                            <h5>Paleta de Cores Principal</h5>
                            <div class="color-palette">
                            {"".join([f'<div class="color-box" style="background:{c};" title="{c}" onclick="copyColor(\'{c}\')"></div>' for c in palette])}
                            </div>
                            
                            <h5>Fontes Utilizadas</h5>
                            <div class="text-item">
                            {"<br>".join(self.global_fonts) if self.global_fonts else "Nenhuma fonte Google Fonts encontrada"}
                            </div>
                            
                            <h5>Logos (Global) - {len(self.global_logos)} encontrados</h5>
                            {self.generate_full_gallery_button('global-logos', list(self.global_logos))}
                            <div class="image-gallery" id="global-logos-preview">
                            {"".join([f'<img src="{l}" onclick="window.open(this.src)">' for l in list(self.global_logos)[:8]]) or "Nenhum logo encontrado"}
                            </div>
                            
                            <h5>Banners (Global) - {len(self.global_banners)} encontrados</h5>
                            {self.generate_full_gallery_button('global-banners', list(self.global_banners))}
                            <div class="image-gallery" id="global-banners-preview">
                            {"".join([f'<img src="{b}" onclick="window.open(this.src)">' for b in list(self.global_banners)[:8]]) or "Nenhum banner encontrado"}
                            </div>
                            
                            <h5>Vídeos (Global) - {len(self.global_videos)} encontrados</h5>
                            <div class="video-container">
                            {self.generate_video_list(list(self.global_videos)[:5])}
                            {f'<p><small>... e mais {len(self.global_videos) - 5} vídeos</small></p>' if len(self.global_videos) > 5 else ''}
                            </div>
                        </div>
                        
                        <div class="text-section">
                            <h4>📈 Estatísticas por Tipo de Página</h4>
                            {self.generate_type_statistics()}
                            
                            <h4>📁 Arquivos Baixados</h4>
                            <div class="text-item">
                                <p><strong>Imagens:</strong> {len(list(self.images_dir.glob('*')))} arquivos</p>
                                <p><strong>Vídeos:</strong> {len(list(self.videos_dir.glob('*')))} arquivos</p>
                                <p><small>Pasta: {self.output.absolute()}</small></p>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- Páginas Individuais -->
                {self.generate_page_sections()}
                
                <div class="footer">
                    <p>Brandbook gerado automaticamente - {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
                    <p><small>Clique nas imagens para abrir em tamanho real | Clique nas cores para copiar o código</small></p>
                </div>
            </div>
            
            <!-- Modais para galerias completas -->
            {self.generate_full_gallery_modals()}
            
            <script>
                function toggleSection(id) {{
                    var section = document.getElementById(id);
                    if (section.style.display === "none" || section.style.display === "") {{
                        section.style.display = "grid";
                    }} else {{
                        section.style.display = "none";
                    }}
                }}
                
                function toggleRanking() {{
                    var content = document.getElementById('ranking-content');
                    var arrow = document.getElementById('ranking-arrow');
                    
                    if (content.classList.contains('expanded')) {{
                        content.classList.remove('expanded');
                        content.classList.add('collapsed');
                        arrow.innerHTML = '▶';
                    }} else {{
                        content.classList.remove('collapsed');
                        content.classList.add('expanded');
                        arrow.innerHTML = '▼';
                    }}
                }}
                
                function copyColor(color) {{
                    navigator.clipboard.writeText(color).then(function() {{
                        alert('Cor ' + color + ' copiada!');
                    }});
                }}
                
                function openGallery(modalId) {{
                    document.getElementById(modalId).style.display = 'block';
                }}
                
                function closeGallery(modalId) {{
                    document.getElementById(modalId).style.display = 'none';
                }}
                
                // Fecha modal ao clicar fora
                window.onclick = function(event) {{
                    if (event.target.classList.contains('full-gallery-modal')) {{
                        event.target.style.display = 'none';
                    }}
                }}
                
                // Expande/recolhe páginas
                document.querySelectorAll('.page-header').forEach(header => {{
                    header.addEventListener('click', function() {{
                        var content = this.nextElementSibling;
                        if (content.style.display === "none" || content.style.display === "") {{
                            content.style.display = "grid";
                        }} else {{
                            content.style.display = "none";
                        }}
                    }});
                }});
            </script>
        </body>
        </html>
        """

        file = self.output / "brandbook.html"
        with open(file, "w", encoding="utf8") as f:
            f.write(html)

        log.info(f"Brandbook gerado em {file}")
        
        # Gera arquivos adicionais
        self.generate_summary_file()
        self.generate_json_export()
    
    def generate_full_gallery_button(self, gallery_id, items):
        """Gera botão para ver galeria completa"""
        if len(items) <= 8:
            return ""
        
        modal_id = f"modal-{gallery_id}"
        return f'<button class="gallery-expand" onclick="openGallery(\'{modal_id}\')">Ver todas as {len(items)} imagens ▶</button>'
    
    def generate_full_gallery_modals(self):
        """Gera modais para galerias completas"""
        modals = ""
        
        # Modal para logos globais
        if len(self.global_logos) > 8:
            modals += f"""
            <div id="modal-global-logos" class="full-gallery-modal">
                <div class="full-gallery-content">
                    <span class="close-modal" onclick="closeGallery('modal-global-logos')">&times;</span>
                    <h3>Todas as Logos ({len(self.global_logos)})</h3>
                    <div class="full-gallery-grid">
                        {"".join([f'<img src="{l}" onclick="window.open(this.src)">' for l in self.global_logos])}
                    </div>
                </div>
            </div>
            """
        
        # Modal para banners globais
        if len(self.global_banners) > 8:
            modals += f"""
            <div id="modal-global-banners" class="full-gallery-modal">
                <div class="full-gallery-content">
                    <span class="close-modal" onclick="closeGallery('modal-global-banners')">&times;</span>
                    <h3>Todos os Banners ({len(self.global_banners)})</h3>
                    <div class="full-gallery-grid">
                        {"".join([f'<img src="{b}" onclick="window.open(this.src)">' for b in self.global_banners])}
                    </div>
                </div>
            </div>
            """
        
        # Modais para cada página
        for i, (url, data) in enumerate(self.page_data.items(), 1):
            if len(data['banners']) > 4:
                modal_id = f"modal-page-{i}-banners"
                modals += f"""
                <div id="{modal_id}" class="full-gallery-modal">
                    <div class="full-gallery-content">
                        <span class="close-modal" onclick="closeGallery('{modal_id}')">&times;</span>
                        <h3>Banners da Página {i}: {data['title'][:50]}</h3>
                        <div class="full-gallery-grid">
                            {"".join([f'<img src="{b}" onclick="window.open(this.src)">' for b in data['banners']])}
                        </div>
                    </div>
                </div>
                """
        
        return modals
    
    def generate_video_list(self, videos):
        """Gera lista de vídeos"""
        if not videos:
            return "<p>Nenhum vídeo encontrado</p>"
        
        video_html = ""
        for v in videos[:5]:
            youtube_id = self.extract_youtube_id(v)
            if youtube_id:
                video_html += f'<div class="video-item">📺 <a href="{v}" target="_blank">YouTube: {youtube_id}</a> <span class="badge badge-youtube">YouTube</span></div>'
            else:
                video_html += f'<div class="video-item">📹 <a href="{v}" target="_blank">{v[:60]}...</a></div>'
        return video_html
    
    def generate_type_statistics(self):
        """Gera estatísticas por tipo de página"""
        stats = defaultdict(lambda: {'count': 0, 'images': 0, 'texts': 0, 'videos': 0})
        
        for url, data in self.page_data.items():
            # Classifica a página pelo path
            parsed = urlparse(url)
            path = parsed.path.strip('/')
            
            if not path:
                page_type = "Home"
            elif any(word in path.lower() for word in ['sobre', 'about', 'empresa']):
                page_type = "Sobre"
            elif any(word in path.lower() for word in ['contato', 'contact', 'fale']):
                page_type = "Contato"
            elif any(word in path.lower() for word in ['produto', 'product', 'servico', 'service']):
                page_type = "Produtos/Serviços"
            elif any(word in path.lower() for word in ['blog', 'noticia', 'news', 'artigo']):
                page_type = "Blog/Notícias"
            else:
                page_type = "Outras"
            
            stats[page_type]['count'] += 1
            stats[page_type]['images'] += len(data['logos']) + len(data['banners']) + len(data['images'])
            stats[page_type]['texts'] += len(data['headings']) + len(data['paragraphs'])
            stats[page_type]['videos'] += len(data['videos'])
        
        html = "<table>"
        html += "<tr><th>Tipo</th><th>Páginas</th><th>Imagens</th><th>Vídeos</th><th>Textos</th></tr>"
        
        for page_type, type_stats in stats.items():
            html += f"<tr><td>{page_type}</td><td>{type_stats['count']}</td><td>{type_stats['images']}</td><td>{type_stats['videos']}</td><td>{type_stats['texts']}</td></tr>"
        
        html += "</table>"
        return html
    
    def generate_toc(self):
        """Gera sumário com links para cada página"""
        toc = ""
        for i, (url, data) in enumerate(self.page_data.items(), 1):
            page_name = data['title'][:50] + "..." if len(data['title']) > 50 else data['title']
            
            # Ícone de importância
            importance_icon = "⭐" if data['importance'] > 50 else "📄"
            
            toc += f'<a href="#page-{i}">{importance_icon} {i}. {page_name}'
            
            if url == self.start_url or url.rstrip('/') == self.start_url.rstrip('/'):
                toc += ' <span class="badge badge-home">Home</span>'
            elif data['importance'] > 30:
                toc += ' <span class="badge badge-important">Importante</span>'
            
            youtube_count = sum(1 for v in data['videos'] if self.extract_youtube_id(v))
            if youtube_count > 0:
                toc += f' <span class="badge badge-youtube">📺 {youtube_count}</span>'
            elif data['videos']:
                toc += f' <span class="badge">📹 {len(data["videos"])}</span>'
            
            toc += '</a>'
        return toc
    
    def generate_page_sections(self):
        """Gera seções HTML para cada página com limites de tamanho"""
        sections = ""
        
        for i, (url, data) in enumerate(self.page_data.items(), 1):
            # Processa dados da página com limites
            unique_headings = []
            seen = set()
            for h in data['headings'][:8]:  # Limite de 8 headings
                key = f"{h['tag']}:{h['text'][:30]}"
                if key not in seen:
                    seen.add(key)
                    unique_headings.append(h)
            
            unique_paragraphs = list(dict.fromkeys(data['paragraphs']))[:5]  # Limite de 5 parágrafos
            unique_buttons = list(dict.fromkeys(data['buttons']))[:6]  # Limite de 6 botões
            
            palette_page = [c for c,_ in Counter(data['colors']).most_common(6)]  # Limite de 6 cores
            
            # Limita número de imagens por categoria
            logos_list = list(data['logos'])[:4]
            banners_list = list(data['banners'])[:4]
            icons_list = list(data['icons'])[:6]
            images_list = list(data['images'])[:6]
            
            # Determina cor da borda baseada na importância
            border_color = "#27ae60" if data['importance'] > 50 else "#3498db" if data['importance'] > 20 else "#95a5a6"
            
            # Botão para ver todos os banners desta página
            banners_button = self.generate_full_gallery_button(f"page-{i}-banners", list(data['banners'])) if len(data['banners']) > 4 else ""
            
            section = f"""
            <div class="page-card" id="page-{i}">
                <div class="page-header" style="background: linear-gradient(135deg, {border_color} 0%, #34495e 100%);">
                    <h3>📄 PÁGINA {i}: {data['title'][:60]}{'...' if len(data['title']) > 60 else ''}</h3>
                    <small>{url[:80]}{'...' if len(url) > 80 else ''}</small>
                    <div>
                        <span class="importance-badge">Importância: {data['importance']}</span>
                        {f'<span class="importance-badge" style="background:#27ae60;">📧 Contato</span>' if data['has_contact_info'] else ''}
                        {f'<span class="importance-badge" style="background:#e74c3c;">📝 Formulário</span>' if data['has_form'] else ''}
                        {f'<span class="importance-badge" style="background:#ff0000;">📺 {len(data["videos"])} Vídeos</span>' if data['videos'] else ''}
                    </div>
                </div>
                
                <div class="page-content">
                    <div class="visual-section">
                        <h4>🎨 Elementos Visuais</h4>
                        
                        {self.generate_image_section('Logos', logos_list, len(data['logos']), '80px')}
                        {self.generate_image_section('Banners', banners_list, len(data['banners']), '100px', banners_button)}
                        {self.generate_image_section('Ícones', icons_list, len(data['icons']), '40px')}
                        {self.generate_image_section('Imagens', images_list, len(data['images']), '80px')}
                        
                        <h5>Cores da Página</h5>
                        <div class="color-palette">
                        {"".join([f'<div class="color-box" style="background:{c};" title="{c}" onclick="copyColor(\'{c}\')"></div>' for c in palette_page]) or "<p>Nenhuma cor encontrada</p>"}
                        {f'<small>+{len(data["colors"]) - len(palette_page)} cores</small>' if len(data['colors']) > len(palette_page) else ''}
                        </div>
                        
                        {self.generate_font_section(data['fonts'])}
                        {self.generate_video_section(data['videos'], data.get('video_files', []))}
                    </div>
                    
                    <div class="text-section">
                        <h4>📝 Conteúdo Textual</h4>
                        
                        {self.generate_meta_section(data)}
                        {self.generate_headings_section(unique_headings, len(data['headings']))}
                        {self.generate_paragraphs_section(unique_paragraphs, len(data['paragraphs']))}
                        {self.generate_buttons_section(unique_buttons, len(data['buttons']))}
                        {self.generate_menu_section(data['menu_items'])}
                        {self.generate_footer_section(data['footer_texts'])}
                    </div>
                </div>
            </div>
            """
            sections += section
        
        return sections
    
    def generate_image_section(self, title, images, total_count, max_size, extra_button=""):
        """Gera seção de imagens com limite"""
        if not images:
            return ""
        
        return f"""
            <h5>{title} {f'({total_count})' if total_count > 0 else ''}</h5>
            {extra_button}
            <div class="image-gallery">
            {"".join([f'<img src="{img}" style="max-width:{max_size}; max-height:{max_size};" onclick="window.open(this.src)">' for img in images])}
            {f'<p><small>... e mais {total_count - len(images)}</small></p>' if total_count > len(images) and not extra_button else ''}
            </div>
        """
    
    def generate_font_section(self, fonts):
        """Gera seção de fontes"""
        if not fonts:
            return ""
        
        fonts_list = list(fonts)[:3]
        return f"""
            <h5>Fontes</h5>
            <div class="text-item">
            {"<br>".join(fonts_list)}
            {f'<br><small>... e mais {len(fonts) - 3}</small>' if len(fonts) > 3 else ''}
            </div>
        """
    
    def generate_video_section(self, videos, video_files):
        """Gera seção de vídeos"""
        if not videos:
            return ""
        
        videos_list = list(videos)[:5]
        videos_html = "<h5>Vídeos</h5><div class='video-container'>"
        
        # Primeiro mostra vídeos baixados localmente
        for vf in video_files[:3]:
            if 'youtube_id' in vf:
                videos_html += f'''
                <div class="video-item">
                    📺 <strong>YouTube BAIXADO:</strong> <a href="{vf['local']}" target="_blank">{vf['local']}</a>
                    <video controls>
                        <source src="{vf['local']}" type="video/mp4">
                    </video>
                    <small class="video-local">YouTube ID: {vf['youtube_id']}</small>
                </div>
                '''
            else:
                videos_html += f'''
                <div class="video-item">
                    📹 <strong>BAIXADO:</strong> <a href="{vf['local']}" target="_blank">{vf['local']}</a>
                    <video controls>
                        <source src="{vf['local']}" type="video/mp4">
                    </video>
                </div>
                '''
        
        # Depois mostra URLs dos vídeos não baixados
        for v in videos_list:
            # Verifica se já foi mostrado como baixado
            if not any(vf['url'] == v for vf in video_files):
                youtube_id = self.extract_youtube_id(v)
                if youtube_id:
                    videos_html += f'<div class="video-item">📺 <a href="{v}" target="_blank">YouTube: {youtube_id}</a> <span class="badge badge-youtube">YouTube</span></div>'
                else:
                    videos_html += f'<div class="video-item">📹 <a href="{v}" target="_blank">{v[:50]}...</a></div>'
        
        if len(videos) > 5:
            videos_html += f'<p><small>... e mais {len(videos) - 5} vídeos</small></p>'
        
        videos_html += "</div>"
        return videos_html
    
    def generate_meta_section(self, data):
        """Gera seção de meta tags"""
        if not data['meta_description'] and not data['meta_keywords']:
            return ""
        
        meta_html = '<div class="meta-info">'
        if data['meta_description']:
            meta_html += f'<p><strong>Meta Description:</strong> {data["meta_description"][:100]}{"..." if len(data["meta_description"]) > 100 else ""}</p>'
        if data['meta_keywords']:
            meta_html += f'<p><strong>Meta Keywords:</strong> {data["meta_keywords"][:100]}{"..." if len(data["meta_keywords"]) > 100 else ""}</p>'
        meta_html += '</div>'
        
        return meta_html
    
    def generate_headings_section(self, headings, total_count):
        """Gera seção de headings"""
        if not headings:
            return ""
        
        headings_html = f"<h5>Títulos {f'({total_count})' if total_count > 0 else ''}</h5>"
        for h in headings:
            headings_html += f'<div class="text-item heading-item"><strong>{h["tag"].upper()}:</strong> {h["text"][:80]}{"..." if len(h["text"]) > 80 else ""}</div>'
        
        if total_count > len(headings):
            headings_html += f'<p><small>... e mais {total_count - len(headings)} títulos</small></p>'
        
        return headings_html
    
    def generate_paragraphs_section(self, paragraphs, total_count):
        """Gera seção de parágrafos"""
        if not paragraphs:
            return ""
        
        paras_html = f"<h5>Parágrafos {f'({total_count})' if total_count > 0 else ''}</h5>"
        for p in paragraphs:
            paras_html += f'<div class="text-item">{p[:120]}{"..." if len(p) > 120 else ""}</div>'
        
        if total_count > len(paragraphs):
            paras_html += f'<p><small>... e mais {total_count - len(paragraphs)} parágrafos</small></p>'
        
        return paras_html
    
    def generate_buttons_section(self, buttons, total_count):
        """Gera seção de botões"""
        if not buttons:
            return ""
        
        buttons_html = f"<h5>Botões {f'({total_count})' if total_count > 0 else ''}</h5>"
        for b in buttons:
            buttons_html += f'<div class="text-item button-item">{b[:60]}{"..." if len(b) > 60 else ""}</div>'
        
        return buttons_html
    
    def generate_menu_section(self, menu_items):
        """Gera seção de menu"""
        if not menu_items:
            return ""
        
        menu_html = "<h5>Menu</h5>"
        if isinstance(menu_items[0], dict):
            for item in menu_items[:5]:
                menu_html += f'<div class="text-item"><a href="{item["url"]}" target="_blank">{item["text"][:40]}</a></div>'
        else:
            for item in menu_items[:5]:
                menu_html += f'<div class="text-item">{item[:50]}</div>'
        
        return menu_html
    
    def generate_footer_section(self, footer_texts):
        """Gera seção de rodapé"""
        if not footer_texts:
            return ""
        
        footer_html = "<h5>Rodapé</h5>"
        for f in footer_texts[:3]:
            footer_html += f'<div class="text-item">{f[:80]}{"..." if len(f) > 80 else ""}</div>'
        
        return footer_html
    
    def generate_summary_file(self):
        """Gera arquivo de resumo com todos os textos"""
        summary_file = self.output / "textos_completos.txt"
        
        with open(summary_file, "w", encoding="utf8") as f:
            f.write(f"RESUMO COMPLETO DE TEXTOS - {self.domain}\n")
            f.write("="*80 + "\n\n")
            
            for i, (url, data) in enumerate(self.page_data.items(), 1):
                f.write(f"\n{'='*80}\n")
                f.write(f"PÁGINA {i}: {data['title']}\n")
                f.write(f"URL: {url}\n")
                f.write(f"Importância: {data['importance']}\n")
                f.write(f"{'='*80}\n\n")
                
                f.write("META DESCRIPTION:\n")
                f.write(f"{data['meta_description'] or 'Não encontrada'}\n\n")
                
                f.write("TÍTULOS:\n")
                for h in data['headings'][:10]:
                    f.write(f"  {h['tag'].upper()}: {h['text']}\n")
                
                f.write("\nPARÁGRAFOS PRINCIPAIS:\n")
                for p in data['paragraphs'][:10]:
                    f.write(f"  • {p}\n\n")
                
                f.write("\nBOTÕES:\n")
                for b in data['buttons'][:8]:
                    f.write(f"  • {b}\n")
                
                f.write(f"\nVÍDEOS ({len(data['videos'])}):\n")
                for v in list(data['videos'])[:5]:
                    youtube_id = self.extract_youtube_id(v)
                    if youtube_id:
                        f.write(f"  • YouTube: {youtube_id}\n")
                    else:
                        f.write(f"  • {v}\n")
                
                f.write("\n" + "="*80 + "\n")
        
        log.info(f"Resumo de textos salvo em {summary_file}")
    
    def generate_json_export(self):
        """Gera exportação em JSON para uso em outras ferramentas"""
        import json
        
        # Converte sets para listas para JSON
        export_data = {
            'domain': self.domain,
            'extraction_date': datetime.now().isoformat(),
            'pages': {},
            'global': {
                'logos': list(self.global_logos)[:50],
                'favicons': list(self.global_favicons),
                'banners': list(self.global_banners)[:50],
                'icons': list(self.global_icons)[:50],
                'images': list(self.global_images)[:100],
                'videos': list(self.global_videos),
                'colors': list(dict.fromkeys(self.global_colors))[:30],
                'fonts': list(self.global_fonts)
            }
        }
        
        for url, data in self.page_data.items():
            # Identifica quais vídeos são do YouTube
            youtube_videos = []
            for v in data['videos']:
                if self.extract_youtube_id(v):
                    youtube_videos.append({
                        'url': v,
                        'youtube_id': self.extract_youtube_id(v)
                    })
            
            export_data['pages'][url] = {
                'title': data['title'],
                'importance': data['importance'],
                'logos': list(data['logos'])[:10],
                'banners': list(data['banners'])[:10],
                'icons': list(data['icons'])[:10],
                'images': list(data['images'])[:20],
                'videos': list(data['videos']),
                'youtube_videos': youtube_videos,
                'video_files': data.get('video_files', []),
                'headings': data['headings'][:15],
                'paragraphs': data['paragraphs'][:10],
                'buttons': data['buttons'][:10],
                'menu_items': data['menu_items'][:10],
                'footer_texts': data['footer_texts'][:5],
                'colors': list(dict.fromkeys(data['colors']))[:15],
                'fonts': list(data['fonts']),
                'meta_description': data['meta_description'],
                'has_form': data['has_form'],
                'has_contact_info': data['has_contact_info']
            }
        
        json_file = self.output / "dados_export.json"
        with open(json_file, "w", encoding="utf8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        log.info(f"Dados exportados para JSON em {json_file}")


# ---------------- RUN ---------------- #

    async def run(self):

        await self.crawl()
        
        # Baixa todos os arquivos (imagens e vídeos)
        await self.download_all_files()

        self.generate_brandbook()

        log.info(f"✅ Processo finalizado! {len(self.page_data)} páginas analisadas.")
        log.info(f"📁 Arquivos salvos em: {self.output.absolute()}")
        log.info(f"   - {len(list(self.images_dir.glob('*')))} imagens baixadas")
        log.info(f"   - {len(list(self.videos_dir.glob('*')))} vídeos baixados")


# ---------------- MAIN ---------------- #

if __name__ == "__main__":

    import sys

    if len(sys.argv) < 2:
        print("Uso:")
        print("python brandbook_extractor.py https://site.com")
        print("\nExemplos:")
        print("  python brandbook_extractor.py https://exemplo.com.br")
        print("  python brandbook_extractor.py exemplo.com.br (adiciona https:// automaticamente)")
        exit()

    url = sys.argv[1]

    extractor = BrandBookExtractor(url)
    asyncio.run(extractor.run())