import { chromium } from 'playwright';

// Armazenamento temporário em memória (em produção, use Redis/KV)
const jobs = new Map();

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Método não permitido' });
  }

  const { sessionToken, anuncios } = req.body;

  if (!sessionToken || !anuncios) {
    return res.status(400).json({ error: 'sessionToken e anuncios são obrigatórios' });
  }

  try {
    const jobId = `job_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    // Inicializar job
    jobs.set(jobId, {
      status: 'pending',
      total: anuncios.length,
      processed: 0,
      photos: 0,
      results: [],
      logs: [],
      startTime: Date.now()
    });

    // Iniciar processamento em background (não esperar)
    processAnuncios(jobId, anuncios, sessionToken).catch(console.error);

    return res.status(200).json({
      success: true,
      jobId,
      message: 'Extração iniciada'
    });

  } catch (error) {
    console.error('Erro ao iniciar extração:', error);
    return res.status(500).json({ error: error.message });
  }
}

async function processAnuncios(jobId, anuncios, sessionToken) {
  let browser = null;
  
  try {
    updateJob(jobId, { status: 'running' });
    addLog(jobId, '🚀 Iniciando processamento...');

    browser = await chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    const page = await browser.newPage();
    const results = [];
    let totalPhotos = 0;

    for (let i = 0; i < anuncios.length; i++) {
      const anuncio = anuncios[i];
      
      addLog(jobId, `⏳ Processando anúncio ${i + 1}/${anuncios.length}: ${anuncio.id}`);

      try {
        await page.goto(anuncio.url, { waitUntil: 'networkidle', timeout: 30000 });
        await page.waitForTimeout(3000);

        // Extrair dados da página
        const dados = await page.evaluate((id) => {
          const texto = document.body.innerText;
          
          // Título
          const titulo = document.querySelector('h1')?.innerText || '';
          
          // Preço
          const precoMatch = texto.match(/Venda[:\s]*R?\$?\s*([\d.,]+)/i);
          const preco = precoMatch ? precoMatch[1].replace(/\./g, '').replace(',', '.') : '';
          
          // Código/Referência
          const refMatch = texto.match(/Ref[.:]\s*([A-Z0-9-]+)/i);
          const codigo = refMatch ? refMatch[1] : id;
          
          // Características
          const quartos = texto.match(/(\d+)\s*quartos?/i)?.[1] || '0';
          const suites = texto.match(/(\d+)\s*(?:suite|suíte)/i)?.[1] || '0';
          const banheiros = texto.match(/(\d+)\s*banheiros?/i)?.[1] || '0';
          const vagas = texto.match(/(\d+)\s*vagas?/i)?.[1] || '0';
          const area = texto.match(/(\d+[.,]?\d*)\s*m[²2]/i)?.[1]?.replace(',', '.') || '0';
          
          // Condomínio
          const condominio = texto.match(/Condom[íi]nio[:\s]*R?\$?\s*([\d.,]+)/i)?.[1]?.replace(/\./g, '').replace(',', '.') || '';
          
          // Endereço
          const enderecoElem = document.querySelector('.endereco-texto');
          const endereco = enderecoElem ? enderecoElem.innerText : '';
          
          // Primeira foto
          const primeiraFoto = document.querySelector('img[src*="imoveis/"]')?.src || '';
          
          return {
            id: codigo,
            titulo,
            preco,
            quartos: parseInt(quartos),
            suites: parseInt(suites),
            banheiros: parseInt(banheiros),
            vagas: parseInt(vagas),
            area: parseFloat(area),
            condominio,
            endereco,
            primeiraFoto
          };
        }, anuncio.id);

        // Gerar URLs das fotos (00 até 99)
        const fotos = [];
        if (dados.primeiraFoto) {
          const baseUrl = dados.primeiraFoto
            .replace(/-(\d{2})\.jpg/, '')
            .replace(/\/(?:\d+x\d+|\w)\//, '/1200x0800/');

          for (let j = 0; j < 30; j++) {
            const num = j.toString().padStart(2, '0');
            const fotoUrl = `${baseUrl}-${num}.jpg`;
            
            try {
              const response = await fetch(fotoUrl, { method: 'HEAD' });
              if (response.ok) {
                fotos.push(fotoUrl);
              } else if (j > 5 && fotos.length === j) {
                break;
              }
            } catch {
              if (j > 5 && fotos.length === j) break;
            }
          }
        }

        results.push({
          ...dados,
          fotos
        });

        totalPhotos += fotos.length;

        updateJob(jobId, {
          processed: i + 1,
          photos: totalPhotos,
          results
        });

        addLog(jobId, `✅ Anúncio ${i + 1} processado - ${fotos.length} fotos`);

      } catch (error) {
        addLog(jobId, `❌ Erro no anúncio ${i + 1}: ${error.message}`);
        
        results.push({
          id: anuncio.id,
          titulo: `Erro ao processar ID ${anuncio.id}`,
          fotos: []
        });
      }

      // Pequena pausa entre anúncios
      await new Promise(r => setTimeout(r, 2000));
    }

    // Gerar XML
    const xml = gerarXML(results);

    updateJob(jobId, {
      status: 'completed',
      xml,
      results
    });

    addLog(jobId, '✅ Extração concluída com sucesso!');

  } catch (error) {
    console.error('Erro no processamento:', error);
    updateJob(jobId, {
      status: 'error',
      error: error.message
    });
  } finally {
    if (browser) await browser.close();
  }
}

function updateJob(jobId, updates) {
  const job = jobs.get(jobId) || {};
  jobs.set(jobId, { ...job, ...updates });
}

function addLog(jobId, message) {
  const job = jobs.get(jobId);
  if (job) {
    job.logs = job.logs || [];
    job.logs.push({ 
      message, 
      timestamp: new Date().toISOString() 
    });
    jobs.set(jobId, job);
  }
}

function gerarXML(imoveis) {
  let xml = '<?xml version="1.0" encoding="UTF-8"?>\n';
  xml += '<ListingDataFeed xmlns="http://www.vivareal.com/schemas/1.0/VRSync" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n';
  xml += '  <Header>\n';
  xml += `    <PublishDate>${new Date().toISOString().slice(0, 19)}</PublishDate>\n`;
  xml += '    <Provider>PLANEJA NEGÓCIOS IMOBILIÁRIOS</Provider>\n';
  xml += '    <Email>planejaimobiliaria@gmail.com</Email>\n';
  xml += '  </Header>\n';
  xml += '  <Listings>\n';

  imoveis.forEach(imovel => {
    xml += '    <Listing>\n';
    xml += `      <ListingID>${escapeXML(imovel.id)}</ListingID>\n`;
    xml += `      <ListDate>${new Date().toISOString().slice(0, 16).replace('T', '-')}</ListDate>\n`;
    xml += `      <LastUpdateDate>${new Date().toISOString().slice(0, 16).replace('T', '-')}</LastUpdateDate>\n`;
    xml += '      <TransactionType>For Sale</TransactionType>\n';
    xml += `      <Title>${escapeXML(imovel.titulo)}</Title>\n`;
    xml += '      <Featured>false</Featured>\n';
    xml += '      <PublicationType>STANDARD</PublicationType>\n';
    
    xml += '      <Location displayAddress="Full">\n';
    xml += '        <Country abbreviation="BR">Brasil</Country>\n';
    xml += '        <State abbreviation="PR">Paraná</State>\n';
    xml += '        <City>Curitiba</City>\n';
    xml += '        <Zone/>\n';
    xml += `        <Neighborhood>${escapeXML(imovel.bairro || '')}</Neighborhood>\n`;
    xml += '        <Address/>\n';
    xml += '        <StreetNumber/>\n';
    xml += '        <Complement/>\n';
    xml += '        <PostalCode/>\n';
    xml += '        <Latitude/>\n';
    xml += '        <Longitude/>\n';
    xml += '      </Location>\n';
    
    xml += '      <Details>\n';
    xml += `        <Description>${escapeXML(imovel.titulo)}</Description>\n`;
    xml += `        <SalePrice currency="BRL">${imovel.preco || '0'}</SalePrice>\n`;
    xml += `        <PropertyType>Apartamento</PropertyType>\n`;
    xml += `        <LivingArea unit="square metres">${imovel.area || '0'}</LivingArea>\n`;
    xml += `        <Bedrooms>${imovel.quartos || 0}</Bedrooms>\n`;
    xml += `        <Bathrooms>${imovel.banheiros || 0}</Bathrooms>\n`;
    xml += `        <Suites>${imovel.suites || 0}</Suites>\n`;
    xml += `        <ParkingSpaces>${imovel.vagas || 0}</ParkingSpaces>\n`;
    xml += `        <MonthlyFee currency="BRL">${imovel.condominio || '0'}</MonthlyFee>\n`;
    xml += '        <Features> </Features>\n';
    xml += '      </Details>\n';
    
    if (imovel.fotos && imovel.fotos.length > 0) {
      xml += '      <Media>\n';
      imovel.fotos.forEach((foto, index) => {
        xml += `        <Item medium="image"${index === 0 ? ' primary="true"' : ''}>${foto}</Item>\n`;
      });
      xml += '      </Media>\n';
    }
    
    xml += '      <ContactInfo>\n';
    xml += '        <Email>planejaimobiliaria@gmail.com</Email>\n';
    xml += '        <Name>PLANEJA NEGÓCIOS IMOBILIÁRIOS</Name>\n';
    xml += '        <Telephone>(41) 3092-1001</Telephone>\n';
    xml += '      </ContactInfo>\n';
    xml += '      <Status>\n';
    xml += '        <PropertyStatus>Available</PropertyStatus>\n';
    xml += `        <StatusDate>${new Date().toLocaleDateString('pt-BR')}</StatusDate>\n`;
    xml += '      </Status>\n';
    xml += '    </Listing>\n';
  });

  xml += '  </Listings>\n';
  xml += '</ListingDataFeed>';
  return xml;
}

function escapeXML(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

// Exportar jobs para outros endpoints
export { jobs };
