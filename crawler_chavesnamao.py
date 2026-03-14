import time
import re
import requests
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime

# ==============================================
# CONFIGURAÇÕES
# ==============================================
EMAIL = "planejaimobiliaria@gmail.com"
SENHA = "18450963"
XML_OUTPUT = "imoveis_vivareal.xml"

class ChavesScraper:
    def __init__(self):
        self.setup_driver()
        self.imoveis = []
        self.session = requests.Session()
        
    def setup_driver(self):
        """Configura o ChromeDriver"""
        options = Options()
        options.add_argument("--start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.wait = WebDriverWait(self.driver, 15)
        
    def login(self):
        """Faz login no site"""
        print("🔐 Fazendo login...")
        self.driver.get("https://www.chavesnamao.com.br/entrar/")
        time.sleep(3)
        
        try:
            botao_email = self.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "span.spacing-1x > button")
            ))
            botao_email.click()
            time.sleep(2)
        except:
            pass
        
        campo_email = self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "#userLogin-input")
        ))
        campo_email.send_keys(EMAIL)
        time.sleep(1)
        
        campo_senha = self.driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        campo_senha.send_keys(SENHA)
        time.sleep(1)
        
        try:
            botao_entrar = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            botao_entrar.click()
        except:
            botao_email.click()
        
        time.sleep(5)
        print("✅ Login realizado!")
        
    def ir_para_meus_anuncios(self):
        """Acessa a página de meus anúncios"""
        print("📋 Acessando Meus Anúncios...")
        self.driver.get("https://www.chavesnamao.com.br/minhaconta/meusanuncios/")
        time.sleep(5)
        
    def extrair_fotos_por_padrao(self, url_primeira_foto):
        """Extrai TODAS as fotos do anúncio usando o padrão sequencial"""
        fotos = []
        
        url_primeira_foto = url_primeira_foto.replace('/0262x0197/', '/1200x0800/')
        url_primeira_foto = url_primeira_foto.replace('/0850x0450/', '/1200x0800/')
        url_primeira_foto = url_primeira_foto.split('?')[0]
        
        match = re.search(r'(.+)-(\d{2})\.jpg', url_primeira_foto)
        if not match:
            fotos.append(url_primeira_foto)
            return fotos
        
        base_url = match.group(1)
        print(f"   📸 Base URL: {base_url}")
        
        for i in range(100):
            numero = str(i).zfill(2)
            foto_url = f"{base_url}-{numero}.jpg"
            
            try:
                response = self.session.head(foto_url, timeout=3)
                if response.status_code == 200:
                    fotos.append(foto_url)
                    print(f"      ✅ Foto {i:02d} encontrada")
                else:
                    if i > 5 and len(fotos) == i:
                        break
            except:
                if i > 5 and len(fotos) == i:
                    break
                continue
        
        print(f"   📸 Total de {len(fotos)} fotos encontradas via padrão")
        return fotos[:30]
    
    def extrair_caracteristicas_extras(self, texto_pagina):
        """Extrai lista de características adicionais"""
        caracteristicas = []
        
        linhas = texto_pagina.split('\n')
        keywords = [
            'recepção', 'portaria', 'refeitório', 'terraço', 'jardim', 
            'sala de reunião', 'estacionamento', 'elevador', 'copa',
            'ar condicionado', 'fechadura biométrica', 'câmeras', 'segurança',
            'cozinha', 'hall', 'acabamento', 'isolamento acústico', 'janelas',
            'banheiro PNE', 'acessibilidade', 'elevador serviço', 'coworking',
            'piscina', 'churrasqueira', 'academia', 'salão de festas',
            'playground', 'quadra', 'sauna', 'gerador', 'cisterna'
        ]
        
        for linha in linhas:
            linha = linha.strip()
            if len(linha) < 5 or len(linha) > 100:
                continue
            
            for keyword in keywords:
                if keyword.lower() in linha.lower():
                    caracteristicas.append(linha)
                    break
        
        return list(set(caracteristicas))[:30]
    
    def extrair_dados_completos(self, id_anuncio):
        """Extrai dados COMPLETOS e REAIS do anúncio"""
        print(f"\n📂 Processando anúncio ID: {id_anuncio}")
        
        dados = {
            'codigo': id_anuncio,
            'titulo': '',
            'descricao': '',
            'tipo': 'Apartamento',
            'subtipo': '',
            'preco_venda': '',
            'preco_locacao': '',
            'cidade': 'Curitiba',
            'bairro': '',
            'logradouro': '',
            'numero': '',
            'complemento': '',
            'cep': '',
            'quartos': 0,
            'suites': 0,
            'banheiros': 0,
            'vagas': 0,
            'area_util': 0,
            'area_total': 0,
            'area_terreno': 0,
            'condominio': '',
            'iptu': '',
            'andar': '',
            'salas': 0,
            'mobiliado': False,
            'caracteristicas_extras': [],
            'fotos': []
        }
        
        try:
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
            time.sleep(2)
            
            texto_pagina = self.driver.find_element(By.TAG_NAME, 'body').text
            print(f"   📄 Analisando página... ({len(texto_pagina)} caracteres)")
            
            # ===== TÍTULO =====
            try:
                titulo_elem = self.driver.find_element(By.CSS_SELECTOR, 'h1')
                dados['titulo'] = titulo_elem.text.strip()
                print(f"   ✅ Título: {dados['titulo'][:80]}...")
            except:
                titulo_pagina = self.driver.title
                if titulo_pagina:
                    dados['titulo'] = titulo_pagina.replace(' | Chaves na Mão', '').strip()
            
            # ===== CÓDIGO/REFERÊNCIA =====
            ref_match = re.search(r'Ref[.:]\s*([A-Z0-9-]+)', texto_pagina, re.I)
            if ref_match:
                dados['codigo'] = ref_match.group(1)
                print(f"   Código: {dados['codigo']}")
            
            # ===== PREÇO =====
            preco_patterns = [
                r'Venda[:\s]*R?\$?\s*([\d.,]+(?:[.,]\d{3})*(?:[.,]\d{2})?)',
                r'R?\$\s*([\d.,]+(?:[.,]\d{3})*(?:[.,]\d{2})?)'
            ]
            
            for pattern in preco_patterns:
                match = re.search(pattern, texto_pagina, re.I)
                if match:
                    valor = match.group(1).replace('.', '').replace(',', '.')
                    if re.match(r'^\d+\.?\d*$', valor):
                        dados['preco_venda'] = valor
                        print(f"   Preço venda: R$ {dados['preco_venda']}")
                        break
            
            # ===== ENDEREÇO =====
            try:
                endereco_elem = self.driver.find_element(By.CSS_SELECTOR, '.endereco-texto, [class*="endereco"]')
                endereco_texto = endereco_elem.text
                
                partes = endereco_texto.split('-')
                if len(partes) >= 2:
                    rua_parts = partes[0].strip().split(',')
                    dados['logradouro'] = rua_parts[0].strip()
                    if len(rua_parts) > 1:
                        dados['numero'] = rua_parts[1].strip()
                    
                    cep_match = re.search(r'\d{5}-?\d{3}', texto_pagina)
                    if cep_match:
                        dados['cep'] = cep_match.group().replace('-', '')
            except:
                pass
            
            # ===== BAIRRO =====
            bairros_conhecidos = [
                'Batel', 'Capão Raso', 'Juvevê', 'Uberaba', 'Água Verde', 
                'Campo Comprido', 'Hugo Lange', 'Ecoville', 'Cabral', 'Centro',
                'Bigorrilho', 'Mercês', 'Boa Vista', 'Cristo Rei', 'Alto da Glória'
            ]
            
            for bairro in bairros_conhecidos:
                if bairro in texto_pagina or bairro in dados['titulo']:
                    dados['bairro'] = bairro
                    break
            
            # ===== CARACTERÍSTICAS =====
            
            # Quartos
            q_match = re.search(r'(\d+)\s*quartos?', texto_pagina, re.I)
            if q_match:
                dados['quartos'] = int(q_match.group(1))
                print(f"   Quartos: {dados['quartos']}")
            
            # Suítes
            s_match = re.search(r'(\d+)\s*suítes?', texto_pagina, re.I)
            if s_match:
                dados['suites'] = int(s_match.group(1))
                print(f"   Suítes: {dados['suites']}")
            
            # Banheiros
            b_match = re.search(r'(\d+)\s*banheiros?', texto_pagina, re.I)
            if b_match:
                dados['banheiros'] = int(b_match.group(1))
                print(f"   Banheiros: {dados['banheiros']}")
            
            # Vagas
            v_match = re.search(r'(\d+)\s*vagas?', texto_pagina, re.I)
            if v_match:
                dados['vagas'] = int(v_match.group(1))
                print(f"   Vagas: {dados['vagas']}")
            
            # Área
            a_match = re.search(r'(\d+[.,]?\d*)\s*m[²2]', texto_pagina, re.I)
            if a_match:
                dados['area_util'] = float(a_match.group(1).replace(',', '.'))
                print(f"   Área: {dados['area_util']}m²")
            
            # Condomínio
            c_match = re.search(r'Condom[íi]nio[:\s]*R?\$?\s*([\d.,]+)', texto_pagina, re.I)
            if c_match:
                dados['condominio'] = c_match.group(1).replace('.', '').replace(',', '.')
                print(f"   Condomínio: R$ {dados['condominio']}")
            
            # IPTU
            i_match = re.search(r'IPTU[:\s]*R?\$?\s*([\d.,]+)', texto_pagina, re.I)
            if i_match:
                dados['iptu'] = i_match.group(1).replace('.', '').replace(',', '.')
                print(f"   IPTU: R$ {dados['iptu']}")
            
            # Andar
            andar_match = re.search(r'(\d+)[º°]?\s*andar', texto_pagina, re.I)
            if andar_match:
                dados['andar'] = andar_match.group(1)
            
            # ===== TIPO =====
            if 'Sala comercial' in texto_pagina:
                dados['tipo'] = 'Comercial'
                dados['subtipo'] = 'Sala Comercial'
            elif 'Cobertura' in texto_pagina:
                dados['tipo'] = 'Cobertura'
                dados['subtipo'] = 'Cobertura'
            elif 'Terreno' in texto_pagina:
                dados['tipo'] = 'Terreno'
                dados['subtipo'] = 'Terreno'
            
            # ===== CARACTERÍSTICAS EXTRAS =====
            dados['caracteristicas_extras'] = self.extrair_caracteristicas_extras(texto_pagina)
            
            # ===== DESCRIÇÃO COMPLETA =====
            descricao_partes = [dados['titulo']]
            
            if dados['codigo'] != id_anuncio:
                descricao_partes.append(f"Referência: {dados['codigo']}")
            
            try:
                desc_elem = self.driver.find_element(By.CSS_SELECTOR, '.descritivo')
                desc_principal = desc_elem.text.strip()
                if desc_principal:
                    descricao_partes.append(desc_principal)
            except:
                pass
            
            if dados['caracteristicas_extras']:
                descricao_partes.append("\nCARACTERÍSTICAS DO IMÓVEL:")
                descricao_partes.extend([f"• {item}" for item in dados['caracteristicas_extras']])
            
            dados['descricao'] = '\n'.join(descricao_partes)
            
            # ===== FOTOS =====
            print("\n📸 Extraindo fotos...")
            
            primeira_foto = None
            imagens = self.driver.find_elements(By.CSS_SELECTOR, 'img[src*="imoveis/"], img[src*="imn/"]')
            
            for img in imagens:
                src = img.get_attribute('src')
                if src and id_anuncio in src and not src.endswith('.png') and not 'logo' in src:
                    primeira_foto = src
                    break
            
            if primeira_foto:
                dados['fotos'] = self.extrair_fotos_por_padrao(primeira_foto)
                print(f"   📸 Total: {len(dados['fotos'])} fotos")
            
        except Exception as e:
            print(f"❌ Erro no anúncio {id_anuncio}: {e}")
        
        return dados
    
    def processar_todos_anuncios(self):
        """Processa todos os anúncios da lista"""
        print("\n🔍 Procurando anúncios...")
        time.sleep(3)
        
        print("📋 Coletando URLs dos anúncios...")
        urls_anuncios = []
        links = self.driver.find_elements(By.CSS_SELECTOR, 'h2.anuncio-titulo a')
        
        for link in links:
            try:
                url = link.get_attribute('href')
                if url:
                    urls_anuncios.append(url)
                    id_match = re.search(r'/(\d+)/', url)
                    if id_match:
                        print(f"   URL encontrada: ID {id_match.group(1)}")
            except:
                continue
        
        print(f"📊 Total de {len(urls_anuncios)} URLs coletadas")
        
        for i, url in enumerate(urls_anuncios):
            print(f"\n{'='*60}")
            print(f"⏳ Processando anúncio {i+1}/{len(urls_anuncios)}")
            
            try:
                self.driver.get(url)
                print(f"   ✅ Abriu URL")
                time.sleep(5)
                
                id_match = re.search(r'/(\d+)/', url)
                id_anuncio = id_match.group(1) if id_match else str(i+1)
                
                dados = self.extrair_dados_completos(id_anuncio)
                
                # SEMPRE adicionar o anúncio, mesmo com dados parciais
                self.imoveis.append(dados)
                print(f"   ✅ Anúncio ADICIONADO! Total na lista: {len(self.imoveis)}")
                
                self.driver.get("https://www.chavesnamao.com.br/minhaconta/meusanuncios/")
                print("   ↩️ Voltando para lista")
                time.sleep(3)
                
            except Exception as e:
                print(f"❌ Erro no anúncio {i+1}: {e}")
                # Adicionar anúncio com dados básicos mesmo em caso de erro
                self.imoveis.append({
                    'codigo': id_anuncio if 'id_anuncio' in locals() else str(i+1),
                    'titulo': f'Imóvel ID {id_anuncio if "id_anuncio" in locals() else i+1}',
                    'descricao': 'Erro ao carregar dados completos',
                    'fotos': []
                })
                try:
                    self.driver.get("https://www.chavesnamao.com.br/minhaconta/meusanuncios/")
                except:
                    pass
                time.sleep(3)
    
    def gerar_xml(self):
        """Gera XML Viva Real com dados COMPLETOS"""
        print("\n📄 Gerando XML...")
        
        if len(self.imoveis) == 0:
            print("❌ Nenhum anúncio para gerar XML!")
            return
        
        now = datetime.now()
        publish_date = now.strftime("%Y-%m-%dT%H:%M:%S")
        list_date = now.strftime("%Y-%m-%d-%H:%M")
        
        root = ET.Element("ListingDataFeed")
        root.set("xmlns", "http://www.vivareal.com/schemas/1.0/VRSync")
        root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
        
        header = ET.SubElement(root, "Header")
        ET.SubElement(header, "PublishDate").text = publish_date
        ET.SubElement(header, "Provider").text = "PLANEJA NEGÓCIOS IMOBILIÁRIOS"
        ET.SubElement(header, "Email").text = EMAIL
        
        listings = ET.SubElement(root, "Listings")
        total_fotos = 0
        
        for idx, imovel in enumerate(self.imoveis):
            print(f"   📝 Adicionando anúncio {idx+1}")
            
            listing = ET.SubElement(listings, "Listing")
            
            ET.SubElement(listing, "ListingID").text = str(imovel.get('codigo', ''))
            ET.SubElement(listing, "ListDate").text = list_date
            ET.SubElement(listing, "LastUpdateDate").text = list_date
            
            # Determinar TransactionType baseado no preço
            if imovel.get('preco_venda'):
                ET.SubElement(listing, "TransactionType").text = "For Sale"
            elif imovel.get('preco_locacao'):
                ET.SubElement(listing, "TransactionType").text = "For Rent"
            else:
                ET.SubElement(listing, "TransactionType").text = "For Sale"
            
            ET.SubElement(listing, "Title").text = imovel.get('titulo', f"Imóvel {imovel.get('codigo', '')}")
            ET.SubElement(listing, "Featured").text = "false"
            ET.SubElement(listing, "PublicationType").text = "STANDARD"
            
            # ===== LOCATION =====
            location = ET.SubElement(listing, "Location")
            location.set("displayAddress", "Full")
            
            country = ET.SubElement(location, "Country")
            country.set("abbreviation", "BR")
            country.text = "Brasil"
            
            state = ET.SubElement(location, "State")
            state.set("abbreviation", "PR")
            state.text = "Paraná"
            
            city = ET.SubElement(location, "City")
            city.text = imovel.get('cidade', 'Curitiba')
            
            ET.SubElement(location, "Zone")
            
            if imovel.get('bairro'):
                neighborhood = ET.SubElement(location, "Neighborhood")
                neighborhood.text = imovel['bairro']
            
            if imovel.get('logradouro'):
                ET.SubElement(location, "Address").text = imovel['logradouro']
            
            if imovel.get('numero'):
                ET.SubElement(location, "StreetNumber").text = imovel['numero']
            
            ET.SubElement(location, "Complement")
            
            if imovel.get('cep'):
                postal = ET.SubElement(location, "PostalCode")
                postal.text = imovel['cep']
            else:
                ET.SubElement(location, "PostalCode")
            
            ET.SubElement(location, "Latitude")
            ET.SubElement(location, "Longitude")
            
            # ===== DETAILS =====
            details = ET.SubElement(listing, "Details")
            
            description = ET.SubElement(details, "Description")
            description.text = imovel.get('descricao', imovel.get('titulo', ''))
            
            if imovel.get('preco_venda'):
                ET.SubElement(details, "SalePrice", currency="BRL").text = imovel['preco_venda']
            
            if imovel.get('preco_locacao'):
                ET.SubElement(details, "RentalPrice", currency="BRL").text = imovel['preco_locacao']
            
            property_type = imovel.get('subtipo', imovel.get('tipo', 'Apartamento'))
            ET.SubElement(details, "PropertyType").text = property_type
            
            if imovel.get('area_util') and imovel['area_util'] > 0:
                ET.SubElement(details, "LivingArea", unit="square metres").text = str(imovel['area_util'])
            
            ET.SubElement(details, "Bedrooms").text = str(imovel.get('quartos', 0))
            ET.SubElement(details, "Bathrooms").text = str(imovel.get('banheiros', 0))
            ET.SubElement(details, "Suites").text = str(imovel.get('suites', 0))
            ET.SubElement(details, "ParkingSpaces").text = str(imovel.get('vagas', 0))
            
            if imovel.get('andar'):
                ET.SubElement(details, "Floor").text = imovel['andar']
            
            if imovel.get('iptu') and imovel['iptu'] != '0':
                ET.SubElement(details, "YearlyTax", currency="BRL").text = imovel['iptu']
            
            if imovel.get('condominio') and imovel['condominio'] != '0':
                ET.SubElement(details, "MonthlyFee", currency="BRL").text = imovel['condominio']
            
            ET.SubElement(details, "Features").text = " "
            
            # ===== MEDIA =====
            if imovel.get('fotos') and len(imovel['fotos']) > 0:
                media = ET.SubElement(listing, "Media")
                for i, foto in enumerate(imovel['fotos'][:30]):
                    item = ET.SubElement(media, "Item", medium="image")
                    if i == 0:
                        item.set("primary", "true")
                    item.text = foto
                total_fotos += len(imovel['fotos'])
            
            # ===== CONTACT INFO =====
            contact = ET.SubElement(listing, "ContactInfo")
            
            contact_email = ET.SubElement(contact, "Email")
            contact_email.text = EMAIL
            
            contact_name = ET.SubElement(contact, "Name")
            contact_name.text = "PLANEJA NEGÓCIOS IMOBILIÁRIOS"
            
            contact_phone = ET.SubElement(contact, "Telephone")
            contact_phone.text = "(41) 3092-1001"
            
            # ===== STATUS =====
            status = ET.SubElement(listing, "Status")
            ET.SubElement(status, "PropertyStatus").text = "Available"
            
            status_date = ET.SubElement(status, "StatusDate")
            status_date.text = now.strftime('%d/%m/%Y')
        
        # Salvar XML
        xml_str = ET.tostring(root, encoding="unicode")
        xml_pretty = minidom.parseString(xml_str).toprettyxml(indent="  ")
        xml_pretty = '\n'.join([line for line in xml_pretty.split('\n') if line.strip()])
        
        caminho_completo = os.path.join(os.getcwd(), XML_OUTPUT)
        with open(XML_OUTPUT, "w", encoding="utf-8") as f:
            f.write(xml_pretty)
        
        print(f"\n{'='*60}")
        print(f"✅ XML gerado com SUCESSO!")
        print(f"📁 Local: {caminho_completo}")
        print(f"📊 Total de anúncios: {len(self.imoveis)}")
        print(f"📸 Total de fotos: {total_fotos}")
        print(f"{'='*60}")
    
    def run(self):
        try:
            self.login()
            self.ir_para_meus_anuncios()
            self.processar_todos_anuncios()
            self.gerar_xml()
            print(f"\n📊 RESUMO FINAL: {len(self.imoveis)} anúncios processados")
            input("\n⏸️  Pressione Enter para fechar...")
        except Exception as e:
            print(f"\n❌ Erro: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("\n🔚 Finalizando...")
            self.driver.quit()

if __name__ == "__main__":
    scraper = ChavesScraper()
    scraper.run()