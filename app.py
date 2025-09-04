import os
import json
import uuid
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
import feedparser
import textwrap

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_super_segura' 
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

# --- Funções de Utilidade e Configuração ---

def inicializar_banco_de_dados():
    """Cria as tabelas do banco de dados se elas não existirem."""
    conn = sqlite3.connect('clientes.db')
    c = conn.cursor()
    # Tabela de Clientes
    c.execute('''
        CREATE TABLE IF NOT EXISTS clientes (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            config TEXT
        )
    ''')
    # Tabela de Feeds com chave estrangeira para o cliente
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

def carregar_configuracoes():
    """Carrega as configurações do arquivo JSON."""
    if not os.path.exists('clientes_config.json'):
        return {}
    with open('clientes_config.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def salvar_configuracoes(config):
    """Salva as configurações no arquivo JSON."""
    with open('clientes_config.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)

configuracoes = carregar_configuracoes()

def verificar_configuracao_completa(cliente_id):
    """Verifica se a configuração essencial do cliente foi preenchida."""
    config = configuracoes.get(cliente_id, {})
    essenciais = ['nome', 'logo_path', 'font_path_titulo', 'font_path_texto']
    return all(key in config and config[key] for key in essenciais)

# --- Rotas da Aplicação ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Lida com o login do cliente ou cria um novo se nenhum ID for fornecido."""
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')

        # Se não foi fornecido um cliente_id, cria um novo
        if not cliente_id:
            cliente_id = f"cliente_{uuid.uuid4().hex[:8]}"
            configuracoes[cliente_id] = {
                'nome': 'Novo Cliente',
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
            
            # **INÍCIO DA CORREÇÃO: Salvar novo cliente no banco de dados**
            try:
                conn = sqlite3.connect('clientes.db')
                c = conn.cursor()
                c.execute("INSERT INTO clientes (id, nome, config) VALUES (?, ?, ?)", 
                          (cliente_id, 'Novo Cliente', json.dumps(configuracoes[cliente_id])))
                conn.commit()
                conn.close()
                print(f"✅ Novo cliente inserido no banco de dados: {cliente_id}")
            except sqlite3.Error as e:
                print(f"❌ Erro ao inserir novo cliente no banco de dados: {e}")
                # Pode-se retornar uma mensagem de erro para o usuário aqui
                return render_template('login.html', erro='Falha ao criar cliente no banco de dados.')
            # **FIM DA CORREÇÃO**
            
            salvar_configuracoes(configuracoes)
            print(f"✅ Novo cliente criado: {cliente_id}")

        # Verifica se o cliente existe
        elif cliente_id not in configuracoes:
            return render_template('login.html', erro='Cliente não encontrado.')

        session['cliente_id'] = cliente_id
        return redirect(url_for('dashboard'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    """Faz o logout do cliente."""
    session.pop('cliente_id', None)
    return redirect(url_for('login'))

@app.route('/')
def dashboard():
    """Exibe o painel principal do cliente."""
    if 'cliente_id' not in session:
        return redirect(url_for('login'))
    
    cliente_id = session['cliente_id']
    config_cliente = configuracoes.get(cliente_id, {})
    config_completa = verificar_configuracao_completa(cliente_id)

    # Buscar feeds do banco de dados
    conn = sqlite3.connect('clientes.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM feeds WHERE cliente_id = ?", (cliente_id,))
    feeds = c.fetchall()
    conn.close()

    # **CORREÇÃO: Listar todos os clientes a partir do banco de dados**
    conn = sqlite3.connect('clientes.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, nome FROM clientes")
    todos_clientes = c.fetchall()
    conn.close()
    
    return render_template('dashboard.html', 
                           cliente_id=cliente_id, 
                           config=config_cliente, 
                           config_completa=config_completa,
                           feeds=feeds,
                           clientes=todos_clientes)

@app.route('/configurar', methods=['GET', 'POST'])
def configurar():
    """Página de configuração do cliente."""
    if 'cliente_id' not in session:
        return redirect(url_for('login'))
    
    cliente_id = session['cliente_id']
    
    if request.method == 'POST':
        # Atualiza o nome do cliente
        configuracoes[cliente_id]['nome'] = request.form['nome']
        
        # Salva o logo
        if 'logo' in request.files and request.files['logo'].filename != '':
            logo = request.files['logo']
            filename = secure_filename(f"{cliente_id}_{logo.filename}")
            logo_path = os.path.join(app.config['UPLOAD_FOLDER'], 'logos', filename)
            os.makedirs(os.path.dirname(logo_path), exist_ok=True)
            logo.save(logo_path)
            configuracoes[cliente_id]['logo_path'] = logo_path
        
        # Salva as fontes
        for tipo_fonte in ['titulo', 'texto']:
            campo_arquivo = f'fonte_{tipo_fonte}'
            if campo_arquivo in request.files and request.files[campo_arquivo].filename != '':
                fonte = request.files[campo_arquivo]
                filename = secure_filename(f"{cliente_id}_{fonte.filename}")
                fonte_path = os.path.join(app.config['UPLOAD_FOLDER'], 'fonts', filename)
                os.makedirs(os.path.dirname(fonte_path), exist_ok=True)
                fonte.save(fonte_path)
                configuracoes[cliente_id][f'font_path_{tipo_fonte}'] = fonte_path

        # Salva outras configurações
        configuracoes[cliente_id]['cor_fundo'] = request.form['cor_fundo']
        configuracoes[cliente_id]['cor_texto_titulo'] = request.form['cor_texto_titulo']
        configuracoes[cliente_id]['cor_texto_noticia'] = request.form['cor_texto_noticia']
        configuracoes[cliente_id]['posicao_logo_x'] = int(request.form['posicao_logo_x'])
        configuracoes[cliente_id]['posicao_logo_y'] = int(request.form['posicao_logo_y'])
        configuracoes[cliente_id]['tamanho_logo'] = int(request.form['tamanho_logo'])
        
        salvar_configuracoes(configuracoes)

        # **Atualizar o banco de dados também**
        try:
            conn = sqlite3.connect('clientes.db')
            c = conn.cursor()
            c.execute("UPDATE clientes SET nome = ?, config = ? WHERE id = ?",
                      (configuracoes[cliente_id]['nome'], json.dumps(configuracoes[cliente_id]), cliente_id))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            print(f"Erro ao atualizar config no DB: {e}")
            
        return redirect(url_for('dashboard'))

    config_cliente = configuracoes.get(cliente_id, {})
    return render_template('configurar.html', config=config_cliente, cliente_id=cliente_id)


@app.route('/adicionar_feed', methods=['POST'])
def adicionar_feed():
    if 'cliente_id' not in session:
        return jsonify({'sucesso': False, 'erro': 'Não autenticado'}), 401

    cliente_id = session['cliente_id']
    url_feed = request.form.get('url_feed')
    tipo_feed = request.form.get('tipo_feed')

    if not url_feed or not tipo_feed:
        return jsonify({'sucesso': False, 'erro': 'URL e tipo do feed são obrigatórios'}), 400

    try:
        conn = sqlite3.connect('clientes.db')
        c = conn.cursor()
        c.execute("INSERT INTO feeds (cliente_id, url, tipo) VALUES (?, ?, ?)",
                  (cliente_id, url_feed, tipo_feed))
        conn.commit()
        conn.close()
        return jsonify({'sucesso': True})
    except sqlite3.Error as e:
        return jsonify({'sucesso': False, 'erro': f'Erro no banco de dados: {e}'}), 500


@app.route('/remover_feed/<int:feed_id>', methods=['POST'])
def remover_feed(feed_id):
    if 'cliente_id' not in session:
        return jsonify({'sucesso': False, 'erro': 'Não autenticado'}), 401
    
    cliente_id = session['cliente_id']
    
    try:
        conn = sqlite3.connect('clientes.db')
        c = conn.cursor()
        # Garante que o usuário só pode remover seus próprios feeds
        c.execute("DELETE FROM feeds WHERE id = ? AND cliente_id = ?", (feed_id, cliente_id))
        conn.commit()
        conn.close()
        if c.rowcount > 0:
            return jsonify({'sucesso': True})
        else:
            return jsonify({'sucesso': False, 'erro': 'Feed não encontrado ou não autorizado'}), 404
    except sqlite3.Error as e:
        return jsonify({'sucesso': False, 'erro': f'Erro no banco de dados: {e}'}), 500

# --- Rotas de Geração de Imagem e Webhook ---

@app.route('/visualizar-imagem')
def visualizar_imagem():
    """Gera e exibe uma imagem de exemplo com base na configuração."""
    if 'cliente_id' not in session:
        return "Não autorizado", 401
    
    cliente_id = session['cliente_id']
    config = configuracoes.get(cliente_id)

    if not config or not verificar_configuracao_completa(cliente_id):
        return "Configuração do cliente incompleta ou não encontrada.", 404

    titulo = "Este é um título de exemplo para a notícia"
    texto = "Este é o texto da notícia de exemplo. Ele serve para demonstrar como o conteúdo será quebrado em várias linhas e exibido na imagem final gerada pelo sistema."

    img = gerar_imagem_noticia(titulo, texto, config)
    
    img_io = BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    
    return send_from_directory('.', 'temp_image.png', as_attachment=False)

@app.route('/webhook-receiver', methods=['POST'])
def webhook_receiver():
    """Recebe dados de notícias via webhook e gera a imagem."""
    data = request.json
    cliente_id = data.get('cliente_id')
    titulo = data.get('titulo')
    texto = data.get('texto')

    if not all([cliente_id, titulo, texto]):
        return jsonify({'erro': 'Dados incompletos'}), 400

    config = configuracoes.get(cliente_id)
    if not config:
        return jsonify({'erro': 'Cliente não encontrado'}), 404

    try:
        gerar_imagem_noticia(titulo, texto, config, f"noticia_{uuid.uuid4().hex[:8]}.png")
        return jsonify({'sucesso': 'Imagem gerada com sucesso'}), 200
    except Exception as e:
        return jsonify({'erro': f'Falha ao gerar imagem: {str(e)}'}), 500

def gerar_imagem_noticia(titulo, texto, config, nome_arquivo='temp_image.png'):
    """Função principal para criar a imagem da notícia."""
    largura, altura = 1080, 1080
    cor_fundo = config.get('cor_fundo', '#FFFFFF')
    
    imagem = Image.new('RGB', (largura, altura), color=cor_fundo)
    draw = ImageDraw.Draw(imagem)

    # Adicionar Logo
    try:
        logo_path = config.get('logo_path')
        if logo_path and os.path.exists(logo_path):
            logo = Image.open(logo_path).convert("RGBA")
            tamanho = config.get('tamanho_logo', 150)
            logo.thumbnail((tamanho, tamanho))
            
            # Máscara para transparência
            if logo.mode == 'RGBA':
                mask = logo.split()[3]
                imagem.paste(logo, (config['posicao_logo_x'], config['posicao_logo_y']), mask)
            else:
                imagem.paste(logo, (config['posicao_logo_x'], config['posicao_logo_y']))
    except Exception as e:
        print(f"Erro ao carregar ou colar o logo: {e}")

    # Adicionar Título
    try:
        fonte_titulo = ImageFont.truetype(config['font_path_titulo'], 60)
        cor_titulo = config['cor_texto_titulo']
        linhas_titulo = textwrap.wrap(titulo, width=35)
        y_text = 200 # Posição inicial do título
        for linha in linhas_titulo:
            draw.text((50, y_text), linha, font=fonte_titulo, fill=cor_titulo)
            y_text += 70
    except Exception as e:
        print(f"Erro ao renderizar título: {e}")

    # Adicionar Texto da Notícia
    try:
        y_text += 20 # Espaço entre título e texto
        fonte_texto = ImageFont.truetype(config['font_path_texto'], 40)
        cor_texto = config['cor_texto_noticia']
        linhas_texto = textwrap.wrap(texto, width=50)
        for linha in linhas_texto:
            draw.text((50, y_text), linha, font=fonte_texto, fill=cor_texto)
            y_text += 50
    except Exception as e:
        print(f"Erro ao renderizar texto da notícia: {e}")

    imagem.save(nome_arquivo)
    return imagem

# --- Rota para servir arquivos estáticos (logos, fontes) ---
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """Serve os arquivos que foram carregados."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    inicializar_banco_de_dados()
    # Garante que os diretórios de upload existam
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'logos'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'fonts'), exist_ok=True)
    app.run(debug=True, port=5001)
