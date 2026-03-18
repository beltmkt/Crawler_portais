import time
import re
import requests
import os
import sys
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime

# ==============================================
# CONFIGURAÇÕES DA API
# ==============================================
app = Flask(__name__)
CORS(app)  # Permite requisições de qualquer origem

# ==============================================
# CLASSE SCRAPER (VERSÃO OTIMIZADA PARA MEMÓRIA)
# ==============================================
class ChavesScraper:
    def __init__(self, email, senha):
        self.email = email
        self.senha = senha
        self.imoveis = []
        self.session = requests.Session()
        self.xml_output = "imoveis_vivareal.xml"
        
    def setup_driver(self):
        """Configura o ChromeDriver com otimizações de memória para o Render"""
        print("🔧 Configurando ChromeDriver (modo econômico)...")
        
        options = Options()
        
        # Configurações headless básicas
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        
        # Otimizações de memória (CRÍTICAS para o Render)
        options.add_argument("--window-size=1280,720")  # Resolução menor
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        options.add_argument("--disk-cache-size=1")
        options.add_argument("--media-cache-size=1")
        options.add_argument("--max_old_space_size=256")  # Limita memória a 256MB
        options.add_argument("--single-process")  # Tenta usar um único processo
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("--disable-logging")
        options.add_argument("--log-level=3")  # Reduz logs
        options.add_argument("--silent")
        
        # User agent
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        
        # Caminho do Chrome (já instalado no Docker)
        chrome_binary = "/usr/bin/google-chrome"
        if os.path.exists(chrome_binary):
            options.binary_location = chrome_binary
            print(f"✅ Chrome encontrado em: {chrome_binary}")
        else:
            print("⚠️ Chrome não encontrado no caminho padrão")
        
        # Caminho FIXO do ChromeDriver (instalado no Docker)
        chromedriver_path = "/usr/local/bin/chromedriver"
        
        if not os.path.exists(chromedriver_path):
            # Fallback: procurar em outros locais
            possible_paths = [
                "/usr/local/bin/chromedriver",
                "/usr/bin/chromedriver",
                "/usr/bin/chromium-driver"
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    chromedriver_path = path
                    break
        
        if not os.path.exists(chromedriver_path):
            raise Exception("❌ ChromeDriver não encontrado em nenhum caminho")
        
        print(f"✅ Usando ChromeDriver em: {chromedriver_path}")
        service = Service(chromedriver_path)
        
        try:
            self.driver = webdriver.Chrome(service=service, options=options)
            self.wait = WebDriverWait(self.driver, 10)  # Timeout reduzido
            print("✅ ChromeDriver configurado com sucesso (modo econômico)!")
        except Exception as e:
            print(f"❌ Erro ao iniciar ChromeDriver: {e}")
            raise
        
    def login(self):
        """Faz login no site com as credenciais recebidas"""
        print("🔐 Fazendo login...")
        self.driver.get("https://www.chavesnamao.com.br/entrar/")
        time.sleep(2)
        
        try:
            botao_email = self.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "span.spacing-1x > button")
            ))
            botao_email.click()
            time.sleep(1)
        except:
            pass
        
        try:
            campo_email = self.wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#userLogin-input")
            ))
            campo_email.send_keys(self.email)
            time.sleep(0.5)
        except:
            print("⚠️ Campo de email não encontrado")
            return False
        
        try:
            campo_senha = self.driver.find_element(By.CSS_SELECTOR, "input[type='password']")
            campo_senha.send_keys(self.senha)
            time.sleep(0.5)
        except:
            print("⚠️ Campo de senha não encontrado")
            return False
        
        try:
            botao_entrar = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            botao_entrar.click()
        except:
            try:
                botao_email.click()
            except:
                pass
        
        time.sleep(3)
        print("✅ Login realizado!")
        return True
        
    def ir_para_meus_anuncios(self):
        """Acessa a página de meus anúncios"""
        print("📋 Acessando Meus Anúncios...")
        self.driver.get("https://www.chavesnamao.com.br/minhaconta/meusanuncios/")
        time.sleep(3)
        
    def extrair_fotos_por_padrao(self, url_primeira_foto):
        """Extrai fotos do anúncio (limitado para economizar memória)"""
        fotos = []
        
        if not url_primeira_foto:
            return fotos
        
        url_primeira_foto = url_primeira_foto.replace('/0262x0197/', '/800x600/')  # Resolução menor
        url_primeira_foto = url_primeira_foto.replace('/0850x0450/', '/800x600/')
        url_primeira_foto = url_primeira_foto.split('?')[0]
        
        match = re.search(r'(.+)-(\d{2})\.jpg', url_primeira_foto)
        if not match:
            fotos.append(url_primeira_foto)
            return fotos[:5]  # Máximo 5 fotos
        
        base_url = match.group(1)
        print(f"   📸 Base URL: {base_url}")
        
        for i in range(10):  # Máximo 10 tentativas
            numero = str(i).zfill(2)
            foto_url = f"{base_url}-{numero}.jpg"
            
            try:
                response = self.session.head(foto_url, timeout=2)
                if response.status_code == 200:
                    fotos.append(foto_url)
                    print(f"      ✅ Foto {i:02d} encontrada")
                else:
                    if i > 3 and len(fotos) == i:
                        break
            except:
                if i > 3 and len(fotos) == i:
                    break
                continue
        
        print(f"   📸 Total de {len(fotos)} fotos encontradas")
        return fotos[:5]  # Máximo 5 fotos
    
    def extrair_caracteristicas_extras(self, texto_pagina):
        """Extrai características principais (limitado)"""
        caracteristicas = []
        
        keywords = [
            'piscina', 'churrasqueira', 'academia', 'salão de festas',
            'portaria', 'elevador', 'ar condicionado', 'câmeras',
            'segurança', 'estacionamento', 'copa', 'cozinha',
            'playground', 'quadra', 'sauna', 'gerador'
        ]
        
        for keyword in keywords:
            if keyword.lower() in texto_pagina.lower():
                caracteristicas.append(keyword)
        
        return caracteristicas[:10]
    
    def extrair_dados_basicos(self, id_anuncio):
        """Extrai dados básicos do anúncio (versão leve)"""
        print(f"\n📂 Processando anúncio ID: {id_anuncio}")
        
        dados = {
            'codigo': id_anuncio,
            'titulo': '',
            'descricao': '',
            'tipo': 'Apartamento',
            'preco_venda': '',
            'cidade': 'Curitiba',
            'bairro': '',
            'quartos': 0,
            'banheiros': 0,
            'vagas': 0,
            'area_util': 0,
            'caracteristicas_extras': [],
            'fotos': []
        }
        
        try:
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
            time.sleep(1)
            
            texto_pagina = self.driver.find_element(By.TAG_NAME, 'body').text
            
            # Título
            try:
                titulo_elem = self.driver.find_element(By.CSS_SELECTOR, 'h1')
                dados['titulo'] = titulo_elem.text.strip()
                print(f"   ✅ Título: {dados['titulo'][:50]}...")
            except:
                pass
            
            # Preço
            preco_match = re.search(r'R?\$\s*([\d.,]+)', texto_pagina)
            if preco_match:
                dados['preco_venda'] = preco_match.group(1)
            
            # Bairro
            bairros = ['Batel', 'Água Verde', 'Centro', 'Bigorrilho', 'Juvevê', 'Cabral']
            for bairro in bairros:
                if bairro in texto_pagina:
                    dados['bairro'] = bairro
                    break
            
            # Quartos
            q_match = re.search(r'(\d+)\s*quartos?', texto_pagina, re.I)
            if q_match:
                dados['quartos'] = int(q_match.group(1))
            
            # Banheiros
            b_match = re.search(r'(\d+)\s*banheiros?', texto_pagina, re.I)
            if b_match:
                dados['banheiros'] = int(b_match.group(1))
            
            # Vagas
            v_match = re.search(r'(\d+)\s*vagas?', texto_pagina, re.I)
            if v_match:
                dados['vagas'] = int(v_match.group(1))
            
            # Área
            a_match = re.search(r'(\d+)\s*m[²2]', texto_pagina, re.I)
            if a_match:
                dados['area_util'] = int(a_match.group(1))
            
            # Características
            dados['caracteristicas_extras'] = self.extrair_caracteristicas_extras(texto_pagina)
            
            # Descrição simples
            dados['descricao'] = dados['titulo']
            if dados['caracteristicas_extras']:
                dados['descricao'] += " - " + ", ".join(dados['caracteristicas_extras'])
            
            # Fotos (apenas primeira)
            try:
                primeira_foto = None
                imagens = self.driver.find_elements(By.CSS_SELECTOR, 'img[src*="imoveis/"]')
                for img in imagens[:3]:
                    src = img.get_attribute('src')
                    if src and id_anuncio in src and not src.endswith('.png'):
                        primeira_foto = src
                        break
                
                if primeira_foto:
                    dados['fotos'] = self.extrair_fotos_por_padrao(primeira_foto)
            except:
                pass
            
        except Exception as e:
            print(f"⚠️ Erro leve no anúncio {id_anuncio}: {e}")
        
        return dados
    
    def processar_anuncios_limitados(self):
        """Processa apenas 1 anúncio para economizar memória"""
        print("\n🔍 Procurando anúncios...")
        time.sleep(2)
        
        print("📋 Coletando URLs...")
        urls_anuncios = []
        
        try:
            links = self.driver.find_elements(By.CSS_SELECTOR, 'h2.anuncio-titulo a')
            for link in links[:3]:  # Pega até 3 para escolher 1
                try:
                    url = link.get_attribute('href')
                    if url and url not in urls_anuncios:
                        urls_anuncios.append(url)
                except:
                    continue
        except:
            pass
        
        # Processa APENAS 1 anúncio (para não estourar memória)
        if urls_anuncios:
            url = urls_anuncios[0]
            print(f"📊 Processando 1 anúncio (modo econômico)")
            
            try:
                self.driver.get(url)
                time.sleep(3)
                
                id_match = re.search(r'/(\d+)/', url)
                id_anuncio = id_match.group(1) if id_match else "1"
                
                dados = self.extrair_dados_basicos(id_anuncio)
                self.imoveis.append(dados)
                print(f"   ✅ Anúncio processado!")
                
            except Exception as e:
                print(f"❌ Erro: {e}")
                self.imoveis.append({
                    'codigo': id_anuncio if 'id_anuncio' in locals() else "1",
                    'titulo': 'Imóvel (processamento limitado)',
                    'descricao': 'Erro ao carregar dados completos',
                    'fotos': []
                })
        else:
            print("❌ Nenhum anúncio encontrado")
    
    def gerar_xml_simples(self):
        """Gera XML simplificado (menos campos)"""
        print("\n📄 Gerando XML simplificado...")
        
        if len(self.imoveis) == 0:
            print("❌ Nenhum anúncio para gerar XML!")
            return None
        
        now = datetime.now()
        
        root = ET.Element("ListingDataFeed")
        root.set("xmlns", "http://www.vivareal.com/schemas/1.0/VRSync")
        
        header = ET.SubElement(root, "Header")
        ET.SubElement(header, "Provider").text = self.email.split('@')[0].upper()
        ET.SubElement(header, "Email").text = self.email
        
        listings = ET.SubElement(root, "Listings")
        
        for imovel in self.imoveis:
            listing = ET.SubElement(listings, "Listing")
            ET.SubElement(listing, "ListingID").text = str(imovel.get('codigo', ''))
            ET.SubElement(listing, "Title").text = imovel.get('titulo', '')
            
            if imovel.get('preco_venda'):
                ET.SubElement(listing, "SalePrice", currency="BRL").text = imovel['preco_venda']
            
            # Location simplificado
            location = ET.SubElement(listing, "Location")
            ET.SubElement(location, "City").text = imovel.get('cidade', 'Curitiba')
            if imovel.get('bairro'):
                ET.SubElement(location, "Neighborhood").text = imovel['bairro']
            
            # Details simplificado
            details = ET.SubElement(listing, "Details")
            ET.SubElement(details, "Description").text = imovel.get('descricao', '')
            
            if imovel.get('quartos'):
                ET.SubElement(details, "Bedrooms").text = str(imovel['quartos'])
            if imovel.get('banheiros'):
                ET.SubElement(details, "Bathrooms").text = str(imovel['banheiros'])
            if imovel.get('vagas'):
                ET.SubElement(details, "ParkingSpaces").text = str(imovel['vagas'])
            if imovel.get('area_util'):
                ET.SubElement(details, "LivingArea", unit="square metres").text = str(imovel['area_util'])
            
            # Fotos (limitado)
            if imovel.get('fotos') and len(imovel['fotos']) > 0:
                media = ET.SubElement(listing, "Media")
                for i, foto in enumerate(imovel['fotos'][:3]):  # Máximo 3 fotos
                    item = ET.SubElement(media, "Item", medium="image")
                    if i == 0:
                        item.set("primary", "true")
                    item.text = foto
            
            # Contact Info
            contact = ET.SubElement(listing, "ContactInfo")
            ET.SubElement(contact, "Email").text = self.email
        
        xml_str = ET.tostring(root, encoding="unicode")
        xml_pretty = minidom.parseString(xml_str).toprettyxml(indent="  ")
        xml_pretty = '\n'.join([line for line in xml_pretty.split('\n') if line.strip()])
        
        print(f"✅ XML gerado com sucesso (versão simplificada)!")
        return xml_pretty
    
    def run(self):
        """Executa o crawler em modo econômico"""
        try:
            self.setup_driver()
            if not self.login():
                return {'success': False, 'error': 'Falha no login'}
            
            self.ir_para_meus_anuncios()
            self.processar_anuncios_limitados()
            xml_content = self.gerar_xml_simples()
            
            return {
                'success': True,
                'total_anuncios': len(self.imoveis),
                'xml': xml_content
            }
            
        except Exception as e:
            print(f"\n❌ Erro: {e}")
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }
            
        finally:
            if hasattr(self, 'driver'):
                try:
                    self.driver.quit()
                except:
                    pass

# ==============================================
# ENDPOINTS DA API
# ==============================================

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'status': 'online',
        'message': 'API do Crawler Chaves na Mão (Modo Econômico)',
        'endpoints': {
            '/scraper': 'POST - Executa o crawler (limitado a 1 anúncio)',
            '/health': 'GET - Verifica status'
        }
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/scraper', methods=['POST'])
def scraper():
    """Endpoint principal para executar o crawler (modo econômico)"""
    try:
        data = request.json
        
        if not data:
            return jsonify({'error': 'JSON inválido ou não fornecido'}), 400
        
        email = data.get('email')
        senha = data.get('senha')
        
        if not email or not senha:
            return jsonify({
                'error': 'Email e senha são obrigatórios',
                'received': data
            }), 400
        
        print(f"\n{'='*60}")
        print(f"🚀 Iniciando crawler (modo econômico) para: {email}")
        print(f"{'='*60}")
        
        scraper = ChavesScraper(email, senha)
        resultado = scraper.run()
        
        if resultado['success']:
            return jsonify({
                'success': True,
                'total_anuncios': resultado['total_anuncios'],
                'xml': resultado['xml'],
                'message': f'{resultado["total_anuncios"]} anúncio(s) processado(s) (modo econômico)'
            })
        else:
            return jsonify({
                'success': False,
                'error': resultado['error'],
                'traceback': resultado.get('traceback', '')
            }), 500
            
    except Exception as e:
        print(f"❌ Erro na API: {e}")
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint não encontrado'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Erro interno do servidor'}), 500

# ==============================================
# PONTO DE ENTRADA
# ==============================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
