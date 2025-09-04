import os
import json
import requests
import textwrap
from flask import (Flask, request, jsonify, render_template, session,
                   redirect, url_for, flash)
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
import uuid
import psycopg2
from psycopg2.extras import DictCursor
import cloudinary
import cloudinary.uploader
import io

# Carrega variáveis de ambiente do arquivo .env (essencial para o Render)
load_dotenv()

app = Flask(__name__)
# É MUITO IMPORTANTE que você defina a variável 'SECRET_KEY' nas configurações do Render
app.secret_key = os.getenv('SECRET_KEY', 'uma-chave-secreta-muito-forte-para-desenvolvimento')

# Configuração do Cloudinary a partir das variáveis de ambiente
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

# --- LÓGICA DE GERAÇÃO DE IMAGEM ---

def baixar_arquivo_url(url):
    """Baixa um arquivo (imagem ou fonte) de uma URL e retorna em bytes."""
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return io.BytesIO(response.content)
    except requests.RequestException as e:
        print(f"Erro ao baixar o arquivo da URL {url}: {e}")
        return None

def gerar_imagem_noticia(titulo, texto, config_cliente):
    """
    Gera uma imagem de notícia personalizada com base na configuração do cliente.
    Esta função agora lida com URLs para logos e fontes.
    """
    # 1. VALIDAÇÃO E CONFIGURAÇÃO
    largura, altura = 1080, 1080
    cor_fundo = config_cliente.get('cor_fundo', '#ffffff')
    cor_texto_titulo = config_cliente.get('cor_texto_titulo', '#000000')
    cor_texto_noticia = config_cliente.get('cor_texto_noticia', '#333333')
    
    logo_url = config_cliente.get('logo_url')
    font_url_titulo = config_cliente.get('font_url_titulo')
    font_url_texto = config_cliente.get('font_url_texto')

    if not all([logo_url, font_url_titulo, font_url_texto]):
        raise ValueError("Configuração incompleta: Faltam URLs para logo ou fontes.")

    # 2. BAIXAR ARQUIVOS DA NUVEM
    logo_bytes = baixar_arquivo_url(logo_url)
    fonte_titulo_bytes = baixar_arquivo_url(font_url_titulo)
    fonte_texto_bytes = baixar_arquivo_url(font_url_texto)

    if not all([logo_bytes, fonte_titulo_bytes, fonte_texto_bytes]):
        raise RuntimeError("Falha ao baixar um ou mais arquivos essenciais (logo, fontes) do Cloudinary.")

    # 3. CRIAÇÃO DA IMAGEM
    imagem = Image.new('RGB', (largura, altura), color=cor_fundo)
    draw = ImageDraw.Draw(imagem)

    # 4. CARREGAR FONTES
    tamanho_fonte_titulo = int(config_cliente.get('tamanho_fonte_titulo', 60))
    tamanho_fonte_texto = int(config_cliente.get('tamanho_fonte_texto', 40))
    
    fonte_titulo_bytes.seek(0)
    fonte_texto_bytes.seek(0)
    
    fonte_titulo = ImageFont.truetype(fonte_titulo_bytes, tamanho_fonte_titulo)
    fonte_texto = ImageFont.truetype(fonte_texto_bytes, tamanho_fonte_texto)

    # 5. ADICIONAR TEXTO (com quebra de linha)
    padding = 60
    max_largura_texto = largura - 2 * padding
    
    # Título
    linhas_titulo = textwrap.wrap(titulo, width=int(max_largura_texto / (tamanho_fonte_titulo * 0.5)))
    y_titulo = 150
    for linha in linhas_titulo:
        draw.text((padding, y_titulo), linha, font=fonte_titulo, fill=cor_texto_titulo)
        y_titulo += fonte_titulo.getbbox(linha)[3] + 10
        
    # Texto/Resumo
    y_texto = y_titulo + 40
    linhas_texto = textwrap.wrap(texto, width=int(max_largura_texto / (tamanho_fonte_texto * 0.6)))
    for linha in linhas_texto:
        draw.text((padding, y_texto), linha, font=fonte_texto, fill=cor_texto_noticia)
        y_texto += fonte_texto.getbbox(linha)[3] + 10

    # 6. ADICIONAR LOGO
    logo_bytes.seek(0)
    logo_img = Image.open(logo_bytes)
    tamanho_logo = int(config_cliente.get('tamanho_logo', 200))
    logo_img.thumbnail((tamanho_logo, tamanho_logo))
    
    pos_x = int(config_cliente.get('posicao_logo_x', largura - tamanho_logo - padding))
    pos_y = int(config_cliente.get('posicao_logo_y', altura - logo_img.height - padding))
    
    # Usa a própria logo como máscara se for PNG com transparência
    if logo_img.mode == 'RGBA':
        imagem.paste(logo_img, (pos_x, pos_y), logo_img)
    else:
        imagem.paste(logo_img, (pos_x, pos_y))

    return imagem

# --- BANCO DE DADOS POSTGRESQL ---

def get_db_connection():
    """Conecta ao banco de dados PostgreSQL usando a URL de conexão do Render."""
    conn_string = os.getenv('DATABASE_URL')
    if not conn_string:
        raise ValueError("ERRO CRÍTICO: A variável de ambiente DATABASE_URL não foi definida!")
    conn = psycopg2.connect(conn_string)
    return conn

def init_db():
    """Cria as tabelas do banco de dados se elas ainda não existirem."""
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
    print("✅ Tabelas do banco de dados verificadas/criadas com sucesso.")

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

    if not cliente:
        session.clear()
        flash("Sua sessão era inválida ou o cliente não foi encontrado. Por favor, faça login novamente.", "warning")
        conn.close()
        return redirect(url_for('login'))

    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM feeds WHERE cliente_id = %s ORDER BY id", (cliente_id,))
        feeds = cur.fetchall()
    conn.close()
    
    config = cliente['config'] or {}
    config_completa = all(k in config and config[k] for k in ['logo_url', 'font_url_titulo', 'font_url_texto'])
    
    return render_template('dashboard.html', config=config, cliente_id=cliente_id, 
                           feeds=feeds, config_completa=config_completa)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        if cliente_id:
            session['cliente_id'] = cliente_id
            return redirect(url_for('dashboard'))
        flash("Por favor, selecione um cliente para continuar.", "warning")

    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute('SELECT id, nome FROM clientes ORDER BY nome')
        clientes = cur.fetchall()
    conn.close()
    return render_template('login.html', clientes=clientes)

@app.route('/logout')
def logout():
    session.clear()
    flash("Você saiu da sua conta.", "info")
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

        flash(f"Cliente '{nome_cliente}' criado! Agora você pode selecioná-lo e configurar os detalhes.", "success")
        return redirect(url_for('login'))
        
    return render_template('adicionar_cliente.html')

@app.route('/configurar', methods=['GET', 'POST'])
def configurar():
    if 'cliente_id' not in session:
        return redirect(url_for('login'))
    
    cliente_id = session['cliente_id']
    
    if request.method == 'POST':
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT config FROM clientes WHERE id = %s", (cliente_id,))
                config_atual = cur.fetchone()['config'] or {}

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
                        flash(f"{tipo.replace('_', ' ').capitalize()} enviado com sucesso!", "info")
                    except Exception as e:
                        flash(f"Erro ao enviar {tipo} para o Cloudinary: {str(e)}", "danger")

            # Atualiza outros campos
            campos_form = ['cor_fundo', 'cor_texto_titulo', 'cor_texto_noticia', 
                           'posicao_logo_x', 'posicao_logo_y', 'tamanho_logo',
                           'tamanho_fonte_titulo', 'tamanho_fonte_texto']
            for campo in campos_form:
                if request.form.get(campo):
                    config_atual[campo] = request.form.get(campo)
            
            with conn.cursor() as cur:
                cur.execute("UPDATE clientes SET nome = %s, config = %s WHERE id = %s",
                            (config_atual['nome'], json.dumps(config_atual), cliente_id))
            conn.commit()
            flash("Configurações salvas com sucesso!", "success")

        except Exception as e:
            flash(f"Ocorreu um erro geral ao salvar: {str(e)}", "danger")
        finally:
            if conn:
                conn.close()
        
        return redirect(url_for('dashboard'))

    else: # GET
        conn = get_db_connection()
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT config FROM clientes WHERE id = %s", (cliente_id,))
            config = cur.fetchone()['config']
        conn.close()
        return render_template('configurar.html', config=config or {}, cliente_id=cliente_id)

@app.route('/adicionar_feed', methods=['POST'])
def adicionar_feed():
    if 'cliente_id' not in session:
        return jsonify(sucesso=False, erro='Não autenticado'), 401
    
    cliente_id = session['cliente_id']
    url_feed = request.form.get('url_feed')
    tipo_feed = request.form.get('tipo_feed')

    if not all([url_feed, tipo_feed]):
        return jsonify(sucesso=False, erro='URL e tipo são obrigatórios'), 400

    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO feeds (cliente_id, url, tipo) VALUES (%s, %s, %s)",
                    (cliente_id, url_feed, tipo_feed))
    conn.commit()
    conn.close()
    flash("Feed adicionado com sucesso!", "success")
    return redirect(url_for('dashboard'))


@app.route('/remover_feed/<int:feed_id>', methods=['POST'])
def remover_feed(feed_id):
    if 'cliente_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM feeds WHERE id = %s AND cliente_id = %s", (feed_id, session['cliente_id']))
    conn.commit()
    conn.close()
    flash("Feed removido.", "info")
    return redirect(url_for('dashboard'))

def initialize_app():
    """Função para ser chamada ANTES de iniciar o servidor Gunicorn no Render."""
    print("🚀 Executando inicialização da aplicação...")
    init_db()

if __name__ == '__main__':
    # Esta linha executa a inicialização quando rodamos localmente
    initialize_app()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
