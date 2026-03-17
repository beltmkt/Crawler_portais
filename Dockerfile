FROM python:3.11-slim

# Instala dependências necessárias
RUN apt-get update && apt-get install -y wget gnupg unzip curl && \
    rm -rf /var/lib/apt/lists/*

# Instala Chrome
RUN wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get update && apt-get install -y /tmp/chrome.deb && \
    rm /tmp/chrome.deb && \
    rm -rf /var/lib/apt/lists/* && \
    echo "✅ Chrome instalado: $(google-chrome --version)"

# Instala ChromeDriver (VERSÃO FIXA - compatível com Chrome 146)
RUN wget -q -O /tmp/chromedriver.zip "https://storage.googleapis.com/chrome-for-testing-public/146.0.7680.80/linux64/chromedriver-linux64.zip" && \
    unzip /tmp/chromedriver.zip -d /usr/local/bin/ && \
    mv /usr/local/bin/chromedriver-linux64/chromedriver /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver && \
    rm -rf /tmp/chromedriver.zip /usr/local/bin/chromedriver-linux64 && \
    echo "✅ ChromeDriver instalado: $(chromedriver --version)"

WORKDIR /app

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o resto do código
COPY . .

# Expõe a porta
EXPOSE 10000

# Comando para iniciar a aplicação
CMD gunicorn crawler_chavesnamao:app --bind 0.0.0.0:$PORT
