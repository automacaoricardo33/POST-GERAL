# ==============================================================================
# BLOCO 1: IMPORTAÇÕES E CONFIGURAÇÃO INICIAL
# ==============================================================================
import os
import io
import json
import requests
import textwrap
from flask import Flask, request, jsonify, render_template, session, redirect, send_from_directory, url_for, flash, send_file
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from base64 import b64encode
import uuid
from datetime import datetime
import sqlite3
import cloudinary
import cloudinary.uploader

# Carrega variáveis de ambiente (essencial para o Render)
load_dotenv()

# --- CONFIGURAÇÃO PARA O RENDER ---
# Define o diretório de dados para usar o Disco Permanente do Render
DATA_DIR = os.environ.get('RENDER_DATA_DIR', '.')
DB_PATH = os.path.join(DATA_DIR, 'clientes.db')
UPLOAD_FOLDER = os.path.join(DATA_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True) # Garante que a pasta de uploads exista

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'sua-chave-secreta-deve-ser-alterada')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Configuração do Cloudinary (usando variáveis de ambiente)
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

# ==============================================================================
# BLOCO 2: BANCO DE DADOS
# ==============================================================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS clientes
                 (id TEXT PRIMARY KEY,
                  nome TEXT UNIQUE,
                  config TEXT,
                  data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS feeds
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  cliente_id TEXT,
                  nome TEXT,
                  url TEXT,
                  tipo TEXT,
                  categoria TEXT,
                  ativo BOOLEAN DEFAULT TRUE,
                  FOREIGN KEY (cliente_id) REFERENCES clientes (id))''')
    conn.commit()
    conn.close()

# Inicializa o DB ao iniciar a aplicação
init_db()

# ==============================================================================
# BLOCO 3: FUNÇÕES AUXILIARES (Criação de Imagem, etc.)
# ==============================================================================
def get_cliente_config(cliente_id):
    conn = get_db_connection()
    cliente_row = conn.execute('SELECT config FROM clientes WHERE id = ?', (cliente_id,)).fetchone()
    conn.close()
    if cliente_row and cliente_row['config']:
        return json.loads(cliente_row['config'])
    return {}

def baixar_imagem(url, timeout=15):
    try:
        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert("RGBA")
    except Exception as e:
        print(f"❌ Erro ao baixar imagem: {e}")
        return None

def criar_imagem_post(config, url_imagem, titulo_post, categoria=None):
    # (Esta função pode ser mantida como está no seu código original,
    # apenas garanta que ela use os caminhos corretos para fontes e logos)
    # ... (Sua lógica de criação de imagem) ...
    # Exemplo simplificado:
    imagem_final = Image.new('RGB', (1080, 1080), color = 'white')
    draw = ImageDraw.Draw(imagem_final)
    fonte = ImageFont.load_default()
    draw.text((50, 50), textwrap.fill(titulo_post, width=40), font=fonte, fill='black')
    
    buffer_saida = io.BytesIO()
    imagem_final.save(buffer_saida, format='JPEG', quality=95)
    return buffer_saida.getvalue()

# ... (Suas outras funções auxiliares como `upload_para_cloudinary`, `publicar_redes_sociais`, etc.)

# ==============================================================================
# BLOCO 4: ROTAS DA INTERFACE WEB
# ==============================================================================

@app.route('/')
def dashboard():
    if 'cliente_id' not in session:
        return redirect(url_for('login'))
    
    cliente_id = session['cliente_id']
    config = get_cliente_config(cliente_id)
    
    conn = get_db_connection()
    feeds = conn.execute("SELECT * FROM feeds WHERE cliente_id = ?", (cliente_id,)).fetchall()
    conn.close()
    
    config_completa = config.get('url_logo') is not None
    
    return render_template('dashboard.html', config=config, cliente_id=cliente_id, 
                          feeds=feeds, config_completa=config_completa)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Simplificando o login - para produção, use um sistema de usuários real
        if request.form.get('username') == 'admin' and request.form.get('password') == 'admin':
            session['cliente_id'] = request.form.get('cliente_id')
            return redirect(url_for('dashboard'))
        else:
            flash("Credenciais inválidas", "danger")

    conn = get_db_connection()
    clientes = conn.execute('SELECT id, nome FROM clientes').fetchall()
    conn.close()
    return render_template('login.html', clientes=clientes)

@app.route('/logout')
def logout():
    session.pop('cliente_id', None)
    return redirect(url_for('login'))

@app.route('/adicionar', methods=['GET', 'POST'])
def adicionar_cliente():
    if request.method == 'POST':
        novo_id = f"cliente_{uuid.uuid4().hex[:8]}"
        nome_cliente = request.form['nome']
        config_inicial = dict(request.form) # Pega todos os dados do formulário

        conn = get_db_connection()
        conn.execute("INSERT INTO clientes (id, nome, config) VALUES (?, ?, ?)",
                     (novo_id, nome_cliente, json.dumps(config_inicial)))
        conn.commit()
        conn.close()

        flash(f"Cliente '{nome_cliente}' criado com sucesso!", "success")
        return redirect(url_for('login'))
        
    return render_template('adicionar_cliente.html')

@app.route('/configurar', methods=['GET', 'POST'])
def configurar():
    if 'cliente_id' not in session:
        return redirect(url_for('login'))
    
    cliente_id = session['cliente_id']
    
    if request.method == 'POST':
        config_atualizada = dict(request.form)
        
        conn = get_db_connection()
        conn.execute("UPDATE clientes SET nome = ?, config = ? WHERE id = ?",
                     (config_atualizada['nome'], json.dumps(config_atualizada), cliente_id))
        conn.commit()
        conn.close()
        
        flash("Configurações salvas com sucesso!", "success")
        return redirect(url_for('dashboard'))
    
    config = get_cliente_config(cliente_id)
    return render_template('configurar.html', config=config, cliente_id=cliente_id)

# ... (Suas outras rotas como adicionar_feed, remover_feed, webhook-receiver, etc.)
# A lógica delas deve permanecer a mesma, pois já interagem com o DB ou com as funções auxiliares.

# ==============================================================================
# BLOCO 5: INICIALIZAÇÃO
# ==============================================================================
if __name__ == '__main__':
    # O Gunicorn (usado pelo Render) vai procurar pelo objeto 'app'
    # app.run() é usado apenas para testes locais
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
