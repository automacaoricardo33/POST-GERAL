import os
import json
import uuid
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, flash
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont
import textwrap
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'agora_sim_uma_chave_super_segura'
app.config['UPLOAD_FOLDER'] = 'uploads'
DB_NAME = 'clientes.db'

# --- Funções de Banco de Dados ---

def get_db_connection():
    """Cria uma conexão com o banco de dados."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def inicializar_banco_de_dados():
    """Cria as tabelas do banco de dados se elas não existirem."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS clientes (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            config TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS feeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id TEXT NOT NULL,
            url TEXT NOT NULL,
            tipo TEXT NOT NULL,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        )
    ''')
    conn.commit()
    conn.close()

def get_cliente_config(cliente_id):
    """Busca a configuração de um cliente específico do banco de dados."""
    conn = get_db_connection()
    cliente = conn.execute('SELECT config FROM clientes WHERE id = ?', (cliente_id,)).fetchone()
    conn.close()
    if cliente and cliente['config']:
        return json.loads(cliente['config'])
    return {}

def verificar_configuracao_completa(config):
    """Verifica se a configuração essencial do cliente foi preenchida."""
    essenciais = ['nome', 'logo_path', 'font_path_titulo', 'font_path_texto']
    return all(key in config and config[key] for key in essenciais)

# --- Rotas da Aplicação ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Página de login para selecionar um cliente."""
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        if cliente_id:
            session['cliente_id'] = cliente_id
            return redirect(url_for('dashboard'))
        else:
            flash('Por favor, selecione um cliente.', 'warning')

    conn = get_db_connection()
    clientes = conn.execute('SELECT id, nome FROM clientes ORDER BY nome').fetchall()
    conn.close()
    return render_template('login.html', clientes=clientes)

@app.route('/adicionar_cliente', methods=['GET', 'POST'])
def adicionar_cliente():
    """Página para criar um novo cliente."""
    if request.method == 'POST':
        nome_cliente = request.form.get('nome_cliente')
        if not nome_cliente:
            flash('O nome do cliente é obrigatório.', 'danger')
            return redirect(url_for('adicionar_cliente'))

        cliente_id = f"cliente_{uuid.uuid4().hex[:8]}"
        config_padrao = {
            'nome': nome_cliente,
            'logo_path': '',
            'font_path_titulo': '',
            'font_path_texto': '',
            'cor_fundo': '#FFFFFF',
            'cor_texto_titulo': '#000000',
            'cor_texto_noticia': '#333333',
            'posicao_logo_x': 10,
            'posicao_logo_y': 10,
            'tamanho_logo': 100
        }

        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO clientes (id, nome, config) VALUES (?, ?, ?)",
                         (cliente_id, nome_cliente, json.dumps(config_padrao)))
            conn.commit()
            flash(f'Cliente "{nome_cliente}" criado com sucesso!', 'success')
        except sqlite3.Error as e:
            flash(f'Erro ao criar cliente: {e}', 'danger')
        finally:
            conn.close()
        
        return redirect(url_for('login'))

    return render_template('adicionar_cliente.html')

@app.route('/logout')
def logout():
    session.pop('cliente_id', None)
    flash('Você saiu da sua conta.', 'info')
    return redirect(url_for('login'))

@app.route('/')
def dashboard():
    if 'cliente_id' not in session:
        return redirect(url_for('login'))
    
    cliente_id = session['cliente_id']
    config_cliente = get_cliente_config(cliente_id)
    config_completa = verificar_configuracao_completa(config_cliente)

    conn = get_db_connection()
    feeds = conn.execute("SELECT * FROM feeds WHERE cliente_id = ?", (cliente_id,)).fetchall()
    conn.close()
    
    return render_template('dashboard.html', 
                           cliente_id=cliente_id, 
                           config=config_cliente, 
                           config_completa=config_completa,
                           feeds=feeds)

@app.route('/configurar', methods=['GET', 'POST'])
def configurar():
    if 'cliente_id' not in session:
        return redirect(url_for('login'))
    
    cliente_id = session['cliente_id']
    config_atual = get_cliente_config(cliente_id)
    
    if request.method == 'POST':
        config_atual['nome'] = request.form['nome']
        
        # Lógica de Upload de Arquivos
        for tipo_arquivo, pasta in [('logo', 'logos'), ('fonte_titulo', 'fonts'), ('fonte_texto', 'fonts')]:
            if tipo_arquivo in request.files and request.files[tipo_arquivo].filename != '':
                arquivo = request.files[tipo_arquivo]
                filename = secure_filename(f"{cliente_id}_{arquivo.filename}")
                path_destino = os.path.join(app.config['UPLOAD_FOLDER'], pasta, filename)
                os.makedirs(os.path.dirname(path_destino), exist_ok=True)
                arquivo.save(path_destino)
                
                # O nome do campo no config é 'logo_path', 'font_path_titulo', etc.
                chave_config = 'logo_path' if tipo_arquivo == 'logo' else f'font_path_{tipo_arquivo.split("_")[1]}'
                config_atual[chave_config] = path_destino

        # Atualiza outras configurações
        config_atual['cor_fundo'] = request.form['cor_fundo']
        config_atual['cor_texto_titulo'] = request.form['cor_texto_titulo']
        config_atual['cor_texto_noticia'] = request.form['cor_texto_noticia']
        config_atual['posicao_logo_x'] = int(request.form['posicao_logo_x'])
        config_atual['posicao_logo_y'] = int(request.form['posicao_logo_y'])
        config_atual['tamanho_logo'] = int(request.form['tamanho_logo'])
        
        # Salva a configuração atualizada no banco de dados
        conn = get_db_connection()
        conn.execute("UPDATE clientes SET nome = ?, config = ? WHERE id = ?",
                     (config_atual['nome'], json.dumps(config_atual), cliente_id))
        conn.commit()
        conn.close()
        
        flash('Configurações salvas com sucesso!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('configurar.html', config=config_atual, cliente_id=cliente_id)


@app.route('/adicionar_feed', methods=['POST'])
def adicionar_feed():
    if 'cliente_id' not in session:
        return jsonify({'sucesso': False, 'erro': 'Não autenticado'}), 401

    cliente_id = session['cliente_id']
    url_feed = request.form.get('url_feed')
    tipo_feed = request.form.get('tipo_feed')

    if not url_feed or not tipo_feed:
        return jsonify({'sucesso': False, 'erro': 'URL e tipo do feed são obrigatórios'}), 400

    conn = get_db_connection()
    conn.execute("INSERT INTO feeds (cliente_id, url, tipo) VALUES (?, ?, ?)",
                 (cliente_id, url_feed, tipo_feed))
    conn.commit()
    conn.close()
    return jsonify({'sucesso': True})


@app.route('/remover_feed/<int:feed_id>', methods=['POST'])
def remover_feed(feed_id):
    if 'cliente_id' not in session:
        return jsonify({'sucesso': False, 'erro': 'Não autenticado'}), 401
    
    conn = get_db_connection()
    conn.execute("DELETE FROM feeds WHERE id = ? AND cliente_id = ?", (feed_id, session['cliente_id']))
    conn.commit()
    conn.close()
    return jsonify({'sucesso': True})

# --- Geração de Imagem e Webhook ---

@app.route('/visualizar-imagem')
def visualizar_imagem():
    if 'cliente_id' not in session:
        return "Não autorizado", 401
    
    config = get_cliente_config(session['cliente_id'])
    if not config or not verificar_configuracao_completa(config):
        flash('Configuração incompleta. Por favor, preencha todos os campos em "Configurar".', 'warning')
        return redirect(url_for('configurar'))

    titulo = "Este é um título de exemplo para a notícia"
    texto = "Este é o texto da notícia de exemplo para demonstrar como o conteúdo será exibido na imagem final."

    try:
        img = gerar_imagem_noticia(titulo, texto, config)
        img_io = BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        return send_file(img_io, mimetype='image/png')
    except Exception as e:
        flash(f"Erro ao gerar imagem: {e}. Verifique os caminhos das fontes.", "danger")
        return redirect(url_for('dashboard'))

def gerar_imagem_noticia(titulo, texto, config):
    largura, altura = 1080, 1080
    imagem = Image.new('RGB', (largura, altura), color=config.get('cor_fundo', '#FFFFFF'))
    draw = ImageDraw.Draw(imagem)

    # Adicionar Logo
    if config.get('logo_path') and os.path.exists(config['logo_path']):
        logo = Image.open(config['logo_path']).convert("RGBA")
        logo.thumbnail((config['tamanho_logo'], config['tamanho_logo']))
        imagem.paste(logo, (config['posicao_logo_x'], config['posicao_logo_y']), logo.split()[3] if logo.mode == 'RGBA' else None)

    # Adicionar Título
    fonte_titulo = ImageFont.truetype(config['font_path_titulo'], 60)
    y_text = 200
    for linha in textwrap.wrap(titulo, width=35):
        draw.text((50, y_text), linha, font=fonte_titulo, fill=config['cor_texto_titulo'])
        y_text += 70
        
    # Adicionar Texto
    y_text += 20
    fonte_texto = ImageFont.truetype(config['font_path_texto'], 40)
    for linha in textwrap.wrap(texto, width=50):
        draw.text((50, y_text), linha, font=fonte_texto, fill=config['cor_texto_noticia'])
        y_text += 50
        
    return imagem

# --- Rotas Utilitárias ---

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    # Garante que os diretórios de upload existam
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'logos'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'fonts'), exist_ok=True)
    inicializar_banco_de_dados()
    app.run(debug=True, port=5001)
