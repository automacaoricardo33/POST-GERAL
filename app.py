import os
import json
import requests
import textwrap
from flask import (Flask, request, jsonify, render_template, session,
                   redirect, url_for, flash, send_file)
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
import uuid
import psycopg2
from psycopg2.extras import DictCursor
import cloudinary
import cloudinary.uploader
import io

# Carrega variáveis de ambiente
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'uma-chave-secreta-muito-forte')

# Configuração do Cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

# --- BANCO DE DADOS POSTGRESQL ---

def get_db_connection():
    """Conecta ao banco de dados PostgreSQL usando a URL do Render."""
    conn_string = os.getenv('DATABASE_URL')
    if not conn_string:
        raise ValueError("Variável de ambiente DATABASE_URL não definida!")
    conn = psycopg2.connect(conn_string)
    return conn

def init_db():
    """Cria as tabelas do banco de dados se não existirem."""
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS clientes (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                config JSONB,
                data_criacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS feeds (
                id SERIAL PRIMARY KEY,
                cliente_id TEXT NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                tipo TEXT NOT NULL,
                data_criacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    conn.commit()
    conn.close()
    print("✅ Tabelas do banco de dados verificadas/criadas.")

# --- ROTAS DA APLICAÇÃO ---

@app.route('/')
def dashboard():
    if 'cliente_id' not in session:
        return redirect(url_for('login'))
    
    cliente_id = session['cliente_id']
    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT nome, config FROM clientes WHERE id = %s", (cliente_id,))
        cliente = cur.fetchone()
        cur.execute("SELECT * FROM feeds WHERE cliente_id = %s", (cliente_id,))
        feeds = cur.fetchall()
    conn.close()
    
    config_completa = cliente['config'].get('logo_url') and cliente['config'].get('font_url_titulo')
    
    return render_template('dashboard.html', config=cliente['config'], cliente_id=cliente_id, 
                           feeds=feeds, config_completa=config_completa)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        if cliente_id:
            session['cliente_id'] = cliente_id
            return redirect(url_for('dashboard'))
        flash("Por favor, selecione um cliente.", "warning")

    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute('SELECT id, nome FROM clientes ORDER BY nome')
        clientes = cur.fetchall()
    conn.close()
    return render_template('login.html', clientes=clientes)

@app.route('/logout')
def logout():
    session.pop('cliente_id', None)
    return redirect(url_for('login'))

@app.route('/adicionar_cliente', methods=['GET', 'POST'])
def adicionar_cliente():
    if request.method == 'POST':
        nome_cliente = request.form.get('nome_cliente')
        if not nome_cliente:
            flash("O nome do cliente é obrigatório.", "danger")
            return redirect(url_for('adicionar_cliente'))

        novo_id = f"cliente_{uuid.uuid4().hex[:8]}"
        config_inicial = {'nome': nome_cliente}

        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO clientes (id, nome, config) VALUES (%s, %s, %s)",
                        (novo_id, nome_cliente, json.dumps(config_inicial)))
        conn.commit()
        conn.close()

        flash(f"Cliente '{nome_cliente}' criado! Agora configure os detalhes.", "success")
        return redirect(url_for('login'))
        
    return render_template('adicionar_cliente.html')

@app.route('/configurar', methods=['GET', 'POST'])
def configurar():
    if 'cliente_id' not in session:
        return redirect(url_for('login'))
    
    cliente_id = session['cliente_id']
    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT config FROM clientes WHERE id = %s", (cliente_id,))
        config_atual = cur.fetchone()['config']

    if request.method == 'POST':
        config_atual['nome'] = request.form.get('nome')
        
        # Upload para Cloudinary
        for tipo in ['logo', 'fonte_titulo', 'fonte_texto']:
            if tipo in request.files and request.files[tipo].filename != '':
                arquivo = request.files[tipo]
                try:
                    upload_result = cloudinary.uploader.upload(
                        arquivo,
                        folder=f"automacao/{cliente_id}",
                        resource_type="raw" if 'fonte' in tipo else 'image'
                    )
                    config_atual[f'{tipo}_url'] = upload_result.get('secure_url')
                    flash(f"{tipo.capitalize()} enviado com sucesso!", "info")
                except Exception as e:
                    flash(f"Erro ao enviar {tipo}: {e}", "danger")

        # Atualiza outras configurações
        campos_form = ['cor_fundo', 'cor_texto_titulo', 'cor_texto_noticia', 
                       'posicao_logo_x', 'posicao_logo_y', 'tamanho_logo']
        for campo in campos_form:
            config_atual[campo] = request.form.get(campo)
        
        with conn.cursor() as cur:
            cur.execute("UPDATE clientes SET nome = %s, config = %s WHERE id = %s",
                        (config_atual['nome'], json.dumps(config_atual), cliente_id))
        conn.commit()
        
        flash("Configurações salvas!", "success")
        return redirect(url_for('dashboard'))

    conn.close()
    return render_template('configurar.html', config=config_atual, cliente_id=cliente_id)

@app.route('/adicionar_feed', methods=['POST'])
def adicionar_feed():
    if 'cliente_id' not in session:
        return jsonify(sucesso=False, erro='Não autenticado'), 401
    cliente_id = session['cliente_id']
    url_feed = request.form.get('url_feed')
    tipo_feed = request.form.get('tipo_feed')

    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO feeds (cliente_id, url, tipo) VALUES (%s, %s, %s)",
                    (cliente_id, url_feed, tipo_feed))
    conn.commit()
    conn.close()
    return jsonify(sucesso=True)

# ... (outras rotas como remover_feed podem ser adaptadas de forma similar) ...

def initialize_app():
    """Função para ser chamada ANTES de iniciar o servidor no Render."""
    print("🚀 Executando inicialização da aplicação...")
    init_db()

# Este comando é crucial para a configuração do Render
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
