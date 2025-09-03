# ==============================================================================
# BLOCO 1: IMPORTAÇÕES
# ==============================================================================
import os
import io
import json
import requests
import textwrap
from flask import Flask, request, jsonify, render_template, session, redirect
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont, ImageOps
from base64 import b64encode
import uuid
from datetime import datetime
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import cloudinary
import cloudinary.uploader
import cloudinary.api

# ==============================================================================
# BLOCO 2: CONFIGURAÇÃO INICIAL
# ==============================================================================
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'chave-secreta-padrao-alterar-em-producao')

# Configuração do Cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

# Configuração do banco de dados
def init_db():
    conn = sqlite3.connect('clientes.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS clientes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  nome TEXT UNIQUE,
                  config TEXT,
                  data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  password_hash TEXT,
                  cliente_id INTEGER,
                  FOREIGN KEY (cliente_id) REFERENCES clientes (id))''')
    
    conn.commit()
    conn.close()

init_db()

print("🚀 INICIANDO SISTEMA DE AUTOMAÇÃO PERSONALIZÁVEL COM CLOUDINARY")

# Configurações padrão
IMG_WIDTH, IMG_HEIGHT = 1080, 1080
CONFIG_FILE = 'clientes_config.json'

# Carregar configurações dos clientes
def carregar_configuracoes():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        return {}
    except json.JSONDecodeError:
        print("❌ Erro ao carregar configurações. Iniciando com configurações vazias.")
        return {}

def salvar_configuracoes(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

# Configurações iniciais
configuracoes = carregar_configuracoes()

# ==============================================================================
# BLOCO 3: FUNÇÕES AUXILIARES
# ==============================================================================
def baixar_imagem(url, timeout=15):
    try:
        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert("RGBA")
    except Exception as e:
        print(f"❌ Erro ao baixar imagem: {e}")
        return None

def upload_para_cloudinary(imagem_bytes, public_id, pasta="automacao_social"):
    try:
        with io.BytesIO(imagem_bytes) as buffer:
            buffer.name = f"{public_id}.jpg"
            buffer.seek(0)
            
            resultado = cloudinary.uploader.upload(
                buffer,
                public_id=public_id,
                folder=pasta,
                overwrite=True,
                resource_type="image"
            )
            
            print(f"✅ Imagem {public_id} enviada para o Cloudinary")
            return resultado['secure_url']
    except Exception as e:
        print(f"❌ Erro ao fazer upload para o Cloudinary: {e}")
        return None

# ... (o resto das funções permanecem iguais)

# ==============================================================================
# BLOCO 4: ROTAS DA INTERFACE WEB
# ==============================================================================
@app.route('/')
def index():
    if 'cliente_id' not in session:
        return render_template('login.html')
    
    cliente_id = session['cliente_id']
    config = configuracoes.get(cliente_id, {})
    return render_template('dashboard.html', config=config, cliente_id=cliente_id)

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    cliente_id = request.form.get('cliente_id')
    
    # Verificação simplificada - em produção usar sistema mais seguro
    if username == 'admin' and password == 'admin':
        # Se não houver cliente_id, criar um novo
        if not cliente_id:
            cliente_id = f"cliente_{uuid.uuid4().hex[:8]}"
            configuracoes[cliente_id] = {
                'nome': 'Novo Cliente',
                'wp_integracao': False,
                'instagram_integracao': False,
                'facebook_integracao': False,
                'cor_fundo': '#FFFFFF',
                'cor_texto': '#000000',
                'cor_destaque': '#d90429',
                'cor_borda': '#000000',
                'espessura_borda': 5,
                'arredondamento_borda': 20,
                'texto_rodape': '@SUAEMPRESA',
                'hashtags_padrao': '#noticias #brasil',
                'tamanho_fonte_titulo': 50,
                'tamanho_fonte_rodape': 30,
            }
            salvar_configuracoes(configuracoes)
        
        session['cliente_id'] = cliente_id
        return jsonify({'sucesso': True, 'cliente_id': cliente_id})
    
    return jsonify({'sucesso': False, 'erro': 'Credenciais inválidas'})

# ... (o resto do código permanece igual)
