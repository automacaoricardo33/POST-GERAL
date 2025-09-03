# ==============================================================================
# BLOCO 1: IMPORTAÇÕES
# ==============================================================================
import os
import io
import json
import requests
import textwrap
from flask import Flask, request, jsonify, render_template, session, redirect, send_from_directory
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

# Configurar pasta de uploads
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'ttf', 'otf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Configuração do banco de dados
def init_db():
    conn = sqlite3.connect('clientes.db')
    c = conn.cursor()
    
    # Tabela de clientes
    c.execute('''CREATE TABLE IF NOT EXISTS clientes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  nome TEXT UNIQUE,
                  config TEXT,
                  data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Tabela de usuários
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  password_hash TEXT,
                  cliente_id INTEGER,
                  FOREIGN KEY (cliente_id) REFERENCES clientes (id))''')
    
    # Tabela de feeds RSS/JSON
    c.execute('''CREATE TABLE IF NOT EXISTS feeds
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  cliente_id TEXT,
                  nome TEXT,
                  url TEXT,
                  tipo TEXT,
                  categoria TEXT,
                  ativo BOOLEAN DEFAULT TRUE,
                  data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
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
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_arquivo(arquivo, pasta):
    if arquivo and allowed_file(arquivo.filename):
        filename = f"{uuid.uuid4().hex}_{arquivo.filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], pasta, filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        arquivo.save(filepath)
        return filename
    return None

def baixar_imagem(url, timeout=15):
    """Baixa uma imagem a partir de uma URL"""
    try:
        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert("RGBA")
    except Exception as e:
        print(f"❌ Erro ao baixar imagem: {e}")
        return None

def upload_para_cloudinary(imagem_bytes, public_id, pasta="automacao_social"):
    """Faz upload de uma imagem para o Cloudinary"""
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

def processar_texto(texto, largura_maxima, fonte):
    """Quebra o texto em linhas com base na largura máxima"""
    draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    palavras = texto.split()
    linhas = []
    linha_atual = []
    
    for palavra in palavras:
        linha_atual.append(palavra)
        teste_linha = ' '.join(linha_atual)
        largura, _ = draw.textsize(teste_linha, font=fonte)
        
        if largura > largura_maxima:
            linha_atual.pop()
            linhas.append(' '.join(linha_atual))
            linha_atual = [palavra]
    
    if linha_atual:
        linhas.append(' '.join(linha_atual))
    
    return linhas

def hex_para_rgb(cor_hex):
    """Converte cor hexadecimal para RGB"""
    cor_hex = cor_hex.lstrip('#')
    return tuple(int(cor_hex[i:i+2], 16) for i in (0, 2, 4))

def carregar_fonte(caminho_fonte, tamanho):
    """Carrega uma fonte do sistema ou da pasta de uploads"""
    try:
        # Primeiro tenta carregar da pasta de uploads
        if os.path.exists(os.path.join(UPLOAD_FOLDER, 'fonts', caminho_fonte)):
            return ImageFont.truetype(os.path.join(UPLOAD_FOLDER, 'fonts', caminho_fonte), tamanho)
        # Se não encontrar, tenta carregar do sistema
        return ImageFont.truetype(caminho_fonte, tamanho)
    except:
        # Fallback para fonte padrão
        return ImageFont.load_default()

def criar_imagem_post(config, url_imagem, titulo_post, categoria=None):
    """Cria imagem personalizada com base nas configurações do cliente"""
    print("🎨 Iniciando criação da imagem personalizada...")
    
    try:
        # Baixar imagens
        imagem_noticia = baixar_imagem(url_imagem)
        
        # Carregar logo
        logo_filename = config.get('logo_filename')
        if logo_filename:
            logo_path = os.path.join(UPLOAD_FOLDER, 'logos', logo_filename)
            logo = Image.open(logo_path).convert("RGBA")
        else:
            # Fallback para logo padrão se não houver
            logo = Image.new('RGBA', (100, 100), (255, 0, 0, 255))
        
        if not imagem_noticia or not logo:
            return None

        # Configurações de design do cliente
        cor_fundo = config.get('cor_fundo', '#FFFFFF')
        cor_texto = config.get('cor_texto', '#000000')
        cor_destaque = config.get('cor_destaque', '#d90429')
        cor_borda = config.get('cor_borda', '#000000')
        cor_categoria = config.get('cor_categoria', '#ff0000')
        espessura_borda = config.get('espessura_borda', 5)
        arredondamento_borda = config.get('arredondamento_borda', 20)
        
        # Carregar fontes
        fonte_titulo_nome = config.get('fonte_titulo', 'Arial')
        fonte_rodape_nome = config.get('fonte_rodape', 'Arial')
        tamanho_fonte_titulo = config.get('tamanho_fonte_titulo', 50)
        tamanho_fonte_rodape = config.get('tamanho_fonte_rodape', 30)
        
        fonte_titulo = carregar_fonte(fonte_titulo_nome, tamanho_fonte_titulo)
        fonte_rodape = carregar_fonte(fonte_rodape_nome, tamanho_fonte_rodape)

        # Criar imagem base
        imagem_final = Image.new('RGBA', (IMG_WIDTH, IMG_HEIGHT), hex_para_rgb(cor_fundo) + (255,))
        draw = ImageDraw.Draw(imagem_final)

        # Adicionar faixa de categoria se fornecida
        pos_img_y = 50
        if categoria:
            altura_faixa = 40
            draw.rectangle([(0, 0), (IMG_WIDTH, altura_faixa)], fill=hex_para_rgb(cor_categoria))
            fonte_categoria = carregar_fonte(fonte_titulo_nome, 25)
            texto_categoria = categoria.upper()
            draw.text((IMG_WIDTH / 2, altura_faixa / 2), texto_categoria, font=fonte_categoria, 
                     fill=hex_para_rgb(cor_texto), anchor="mm")
            pos_img_y += altura_faixa + 10

        # Redimensionar e posicionar imagem da notícia
        img_w, img_h = 980, 551
        imagem_noticia_resized = imagem_noticia.resize((img_w, img_h))
        pos_img_x = (IMG_WIDTH - img_w) // 2
        imagem_final.paste(imagem_noticia_resized, (pos_img_x, pos_img_y))

        # Adicionar borda se configurado
        if espessura_borda > 0:
            borda = ImageOps.expand(imagem_noticia_resized, border=espessura_borda, fill=hex_para_rgb(cor_borda))
            imagem_final.paste(borda, (pos_img_x - espessura_borda, pos_img_y - espessura_borda))

        # Área de texto personalizável
        box_texto_coords = [(50, 620), (IMG_WIDTH - 50, IMG_HEIGHT - 50)]
        draw.rounded_rectangle(box_texto_coords, radius=arredondamento_borda, fill=hex_para_rgb(cor_destaque))

        # Logo (elevado)
        logo_size = 220
        logo.thumbnail((logo_size, logo_size))
        pos_logo_x = (IMG_WIDTH - logo_size) // 2
        pos_logo_y = 620 - (logo_size // 2) - 20  # Eleva o logo
        imagem_final.paste(logo, (pos_logo_x, pos_logo_y), logo)

        # Título com quebra de linha personalizada
        linhas_texto = processar_texto(titulo_post.upper(), 900, fonte_titulo)
        y_texto = 800
        for linha in linhas_texto:
            draw.text((IMG_WIDTH / 2, y_texto), linha, font=fonte_titulo, fill=hex_para_rgb(cor_texto), anchor="mm", align="center")
            y_texto += fonte_titulo.getsize(linha)[1] + 10

        # Rodape personalizado
        rodape = config.get('texto_rodape', '@SUAEMPRESA')
        draw.text((IMG_WIDTH / 2, 980), rodape, font=fonte_rodape, fill=hex_para_rgb(cor_texto), anchor="ms", align="center")

        # Salvar imagem
        buffer_saida = io.BytesIO()
        imagem_final.convert('RGB').save(buffer_saida, format='JPEG', quality=95)
        print("✅ Imagem personalizada criada com sucesso!")
        return buffer_saida.getvalue()
        
    except Exception as e:
        print(f"❌ Erro na criação da imagem: {e}")
        return None

def publicar_redes_sociais(config, url_imagem, titulo, resumo, hashtags):
    """Publica nas redes sociais com base nas configurações"""
    resultados = {}
    
    # WordPress
    if config.get('wp_integracao', False):
        wp_url = config.get('wp_url')
        wp_user = config.get('wp_user')
        wp_password = config.get('wp_password')
        
        if all([wp_url, wp_user, wp_password]):
            try:
                credentials = f"{wp_user}:{wp_password}"
                token_wp = b64encode(credentials.encode())
                headers_wp = {'Authorization': f'Basic {token_wp.decode("utf-8")}'}
                
                # Fazer upload para WordPress
                nome_arquivo = f"post_social_{int(datetime.now().timestamp())}.jpg"
                url_wp_media = f"{wp_url}/wp-json/wp/v2/media"
                headers_upload = headers_wp.copy()
                headers_upload['Content-Disposition'] = f'attachment; filename={nome_arquivo}'
                headers_upload['Content-Type'] = 'image/jpeg'
                
                # Baixar imagem do Cloudinary para enviar ao WordPress
                response_img = requests.get(url_imagem)
                if response_img.status_code == 200:
                    response = requests.post(url_wp_media, headers=headers_upload, data=response_img.content, timeout=30)
                    response.raise_for_status()
                    link_imagem_publica = response.json()['source_url']
                    resultados['wordpress'] = {'sucesso': True, 'url': link_imagem_publica}
                else:
                    resultados['wordpress'] = {'sucesso': False, 'erro': 'Falha ao baixar imagem do Cloudinary'}
            except Exception as e:
                resultados['wordpress'] = {'sucesso': False, 'erro': str(e)}
    
    # Instagram
    if config.get('instagram_integracao', False):
        meta_token = config.get('meta_token')
        instagram_id = config.get('instagram_id')
        
        if all([meta_token, instagram_id]):
            try:
                # Criar container de mídia
                url_container = f"https://graph.facebook.com/v19.0/{instagram_id}/media"
                legenda = f"{titulo}\n\n{resumo}\n\n{hashtags}"
                params_container = {'image_url': url_imagem, 'caption': legenda, 'access_token': meta_token}
                r_container = requests.post(url_container, params=params_container, timeout=20)
                r_container.raise_for_status()
                id_criacao = r_container.json()['id']
                
                # Publicar
                url_publicacao = f"https://graph.facebook.com/v19.0/{instagram_id}/media_publish"
                params_publicacao = {'creation_id': id_criacao, 'access_token': meta_token}
                r_publish = requests.post(url_publicacao, params=params_publicacao, timeout=20)
                r_publish.raise_for_status()
                resultados['instagram'] = {'sucesso': True}
            except Exception as e:
                resultados['instagram'] = {'sucesso': False, 'erro': str(e)}
    
    # Facebook
    if config.get('facebook_integracao', False):
        meta_token = config.get('meta_token')
        facebook_page_id = config.get('facebook_page_id')
        
        if all([meta_token, facebook_page_id]):
            try:
                url_post_foto = f"https://graph.facebook.com/v19.0/{facebook_page_id}/photos"
                legenda = f"{titulo}\n\n{resumo}\n\n{hashtags}"
                params = {'url': url_imagem, 'message': legenda, 'access_token': meta_token}
                r = requests.post(url_post_foto, params=params, timeout=20)
                r.raise_for_status()
                resultados['facebook'] = {'sucesso': True}
            except Exception as e:
                resultados['facebook'] = {'sucesso': False, 'erro': str(e)}
    
    return resultados

def processar_feed_rss(url_feed, limite=5):
    """Processa um feed RSS usando BeautifulSoup em vez de feedparser"""
    try:
        response = requests.get(url_feed, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'xml')
        noticias = []
        
        for entrada in soup.find_all('item')[:limite]:
            # Extrair informações básicas
            titulo = entrada.find('title')
            resumo = entrada.find('description')
            link = entrada.find('link')
            data = entrada.find('pubDate')
            
            # Tentar encontrar uma imagem
            imagem = None
            
            # Verificar tag media:content
            media_content = entrada.find('media:content')
            if media_content and media_content.get('url'):
                imagem = media_content.get('url')
            
            # Verificar tag enclosure
            if not imagem:
                enclosure = entrada.find('enclosure')
                if enclosure and 'image' in enclosure.get('type', ''):
                    imagem = enclosure.get('url')
            
            # Procurar imagem no conteúdo
            if not imagem:
                content = entrada.find('content:encoded')
                if not content:
                    content = resumo
                if content:
                    content_soup = BeautifulSoup(content.text, 'html.parser')
                    img = content_soup.find('img')
                    if img:
                        imagem = img.get('src')
            
            noticia = {
                'titulo': titulo.text if titulo else 'Sem título',
                'resumo': resumo.text if resumo else '',
                'link': link.text if link else '',
                'data': data.text if data else '',
                'imagem': imagem
            }
            noticias.append(noticia)
        
        return noticias
    except Exception as e:
        print(f"❌ Erro ao processar feed RSS: {e}")
        return []

def processar_json_noticias(url_json, limite=5):
    """Processa um JSON de notícias e retorna as últimas"""
    try:
        response = requests.get(url_json, timeout=10)
        response.raise_for_status()
        dados = response.json()
        
        noticias = []
        for item in dados[:limite]:
            noticia = {
                'titulo': item.get('title', ''),
                'resumo': item.get('summary', ''),
                'link': item.get('link', ''),
                'data': item.get('date', ''),
                'imagem': item.get('image', '')
            }
            noticias.append(noticia)
        
        return noticias
    except Exception as e:
        print(f"❌ Erro ao processar JSON: {e}")
        return []

# ==============================================================================
# BLOCO 4: ROTAS DA INTERFACE WEB
# ==============================================================================
@app.route('/')
def index():
    if 'cliente_id' not in session:
        return render_template('login.html')
    
    cliente_id = session['cliente_id']
    config = configuracoes.get(cliente_id, {})
    
    # Conectar ao banco de dados para obter feeds
    conn = sqlite3.connect('clientes.db')
    c = conn.cursor()
    c.execute("SELECT * FROM feeds WHERE cliente_id = ?", (cliente_id,))
    feeds = c.fetchall()
    conn.close()
    
    return render_template('dashboard.html', config=config, cliente_id=cliente_id, feeds=feeds)

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    cliente_id = request.form.get('cliente_id', '').strip()
    
    # Verificar credenciais
    if username != 'admin' or password != 'admin':
        return jsonify({'sucesso': False, 'erro': 'Credenciais inválidas'})
    
    # Se não foi fornecido um cliente_id, criar um novo
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
            'cor_categoria': '#ff0000',
            'espessura_borda': 5,
            'arredondamento_borda': 20,
            'texto_rodape': '@SUAEMPRESA',
            'hashtags_padrao': '#noticias #brasil',
            'tamanho_fonte_titulo': 50,
            'tamanho_fonte_rodape': 30,
        }
        salvar_configuracoes(configuracoes)
        print(f"✅ Novo cliente criado: {cliente_id}")
    
    # Verificar se o cliente_id existe nas configurações
    if cliente_id not in configuracoes:
        return jsonify({'sucesso': False, 'erro': 'Cliente ID não encontrado'})
    
    # Login bem-sucedido
    session['cliente_id'] = cliente_id
    return jsonify({
        'sucesso': True, 
        'cliente_id': cliente_id,
        'mensagem': 'Login realizado com sucesso'
    })

@app.route('/logout')
def logout():
    session.pop('cliente_id', None)
    return redirect('/')

@app.route('/configurar', methods=['GET', 'POST'])
def configurar():
    if 'cliente_id' not in session:
        return redirect('/')
    
    cliente_id = session['cliente_id']
    
    if request.method == 'POST':
        # Processar uploads de arquivos
        logo_arquivo = request.files.get('logo_arquivo')
        fonte_titulo_arquivo = request.files.get('fonte_titulo_arquivo')
        fonte_rodape_arquivo = request.files.get('fonte_rodape_arquivo')
        
        logo_filename = None
        fonte_titulo_filename = None
        fonte_rodape_filename = None
        
        if logo_arquivo and allowed_file(logo_arquivo.filename):
            logo_filename = upload_arquivo(logo_arquivo, 'logos')
        
        if fonte_titulo_arquivo and allowed_file(fonte_titulo_arquivo.filename):
            fonte_titulo_filename = upload_arquivo(fonte_titulo_arquivo, 'fonts')
        
        if fonte_rodape_arquivo and allowed_file(fonte_rodape_arquivo.filename):
            fonte_rodape_filename = upload_arquivo(fonte_rodape_arquivo, 'fonts')
        
        # Salvar configurações
        nova_config = {
            'nome': request.form.get('nome_cliente'),
            'wp_url': request.form.get('wp_url'),
            'wp_user': request.form.get('wp_user'),
            'wp_password': request.form.get('wp_password'),
            'wp_integracao': request.form.get('wp_integracao') == 'on',
            'meta_token': request.form.get('meta_token'),
            'instagram_id': request.form.get('instagram_id'),
            'facebook_page_id': request.form.get('facebook_page_id'),
            'instagram_integracao': request.form.get('instagram_integracao') == 'on',
            'facebook_integracao': request.form.get('facebook_integracao') == 'on',
            'cor_fundo': request.form.get('cor_fundo'),
            'cor_texto': request.form.get('cor_texto'),
            'cor_destaque': request.form.get('cor_destaque'),
            'cor_borda': request.form.get('cor_borda'),
            'cor_categoria': request.form.get('cor_categoria'),
            'espessura_borda': int(request.form.get('espessura_borda', 5)),
            'arredondamento_borda': int(request.form.get('arredondamento_borda', 20)),
            'texto_rodape': request.form.get('texto_rodape'),
            'hashtags_padrao': request.form.get('hashtags_padrao'),
            'tamanho_fonte_titulo': int(request.form.get('tamanho_fonte_titulo', 50)),
            'tamanho_fonte_rodape': int(request.form.get('tamanho_fonte_rodape', 30)),
        }
        
        # Adicionar nomes de arquivos se foram enviados
        if logo_filename:
            nova_config['logo_filename'] = logo_filename
        
        if fonte_titulo_filename:
            nova_config['fonte_titulo'] = fonte_titulo_filename
        else:
            nova_config['fonte_titulo'] = request.form.get('fonte_titulo')
        
        if fonte_rodape_filename:
            nova_config['fonte_rodape'] = fonte_rodape_filename
        else:
            nova_config['fonte_rodape'] = request.form.get('fonte_rodape')
        
        configuracoes[cliente_id] = nova_config
        salvar_configuracoes(configuracoes)
        
        return jsonify({'sucesso': True})
    
    config = configuracoes.get(cliente_id, {})
    
    # Listar fontes disponíveis
    fontes_disponiveis = []
    fontes_path = os.path.join(UPLOAD_FOLDER, 'fonts')
    if os.path.exists(fontes_path):
        fontes_disponiveis = [f for f in os.listdir(fontes_path) if f.endswith(('.ttf', '.otf'))]
    
    return render_template('configurar.html', config=config, fontes_disponiveis=fontes_disponiveis)

@app.route('/uploads/<path:filename>')
def download_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/adicionar-feed', methods=['POST'])
def adicionar_feed():
    if 'cliente_id' not in session:
        return jsonify({'sucesso': False, 'erro': 'Não autorizado'}), 403
    
    cliente_id = session['cliente_id']
    nome = request.form.get('nome')
    url = request.form.get('url')
    tipo = request.form.get('tipo')
    categoria = request.form.get('categoria')
    
    if not all([nome, url, tipo]):
        return jsonify({'sucesso': False, 'erro': 'Dados incompletos'}), 400
    
    # Conectar ao banco de dados
    conn = sqlite3.connect('clientes.db')
    c = conn.cursor()
    c.execute("INSERT INTO feeds (cliente_id, nome, url, tipo, categoria) VALUES (?, ?, ?, ?, ?)",
              (cliente_id, nome, url, tipo, categoria))
    conn.commit()
    conn.close()
    
    return jsonify({'sucesso': True})

@app.route('/remover-feed/<int:feed_id>', methods=['DELETE'])
def remover_feed(feed_id):
    if 'cliente_id' not in session:
        return jsonify({'sucesso': False, 'erro': 'Não autorizado'}), 403
    
    # Conectar ao banco de dados
    conn = sqlite3.connect('clientes.db')
    c = conn.cursor()
    c.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'sucesso': True})

@app.route('/webhook-receiver', methods=['POST'])
def webhook_receiver():
    print("\n" + "="*50)
    print("🔔 Webhook recebido!")
    
    try:
        dados = request.json
        cliente_id = dados.get('cliente_id')
        
        if not cliente_id or cliente_id not in configuracoes:
            return jsonify({"status": "erro", "mensagem": "Cliente não configurado"}), 400
        
        config = configuracoes[cliente_id]
        
        # Extrair dados do post
        post_id = dados.get('post_id')
        titulo_noticia = dados.get('titulo', '')
        resumo_noticia = dados.get('resumo', '')
        url_imagem_destaque = dados.get('imagem_destaque', '')
        categoria = dados.get('categoria', '')
        hashtags = dados.get('hashtags', config.get('hashtags_padrao', ''))
        
        if not all([post_id, titulo_noticia, url_imagem_destaque]):
            return jsonify({"status": "erro", "mensagem": "Dados incompletos"}), 400
        
        print(f"✅ Processando post ID: {post_id} para o cliente: {cliente_id}")
        
        # Criar imagem
        imagem_bytes = criar_imagem_post(config, url_imagem_destaque, titulo_noticia, categoria)
        if not imagem_bytes:
            return jsonify({"status": "erro", "mensagem": "Falha ao criar imagem"}), 500
        
        # Fazer upload para o Cloudinary
        nome_arquivo = f"{cliente_id}_{post_id}_{int(datetime.now().timestamp())}"
        url_imagem_cloudinary = upload_para_cloudinary(imagem_bytes, nome_arquivo)
        
        if not url_imagem_cloudinary:
            return jsonify({"status": "erro", "mensagem": "Falha ao fazer upload para o Cloudinary"}), 500
        
        # Publicar nas redes sociais
        resultados = publicar_redes_sociais(config, url_imagem_cloudinary, titulo_noticia, resumo_noticia, hashtags)
        
        # Verificar resultados
        sucessos = [r for r in resultados.values() if r.get('sucesso')]
        if sucessos:
            print("🎉 Publicação bem-sucedida em pelo menos uma rede social!")
            return jsonify({"status": "sucesso", "resultados": resultados}), 200
        else:
            print("❌ Falha em todas as tentativas de publicação")
            return jsonify({"status": "erro", "resultados": resultados}), 500
            
    except Exception as e:
        print(f"❌ Erro crítico: {e}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/testar-feed', methods=['POST'])
def testar_feed():
    if 'cliente_id' not in session:
        return jsonify({'sucesso': False, 'erro': 'Não autorizado'}), 403
    
    url = request.form.get('url')
    tipo = request.form.get('tipo')
    
    if not url or not tipo:
        return jsonify({'sucesso': False, 'erro': 'URL e tipo são obrigatórios'}), 400
    
    try:
        if tipo == 'rss':
            noticias = processar_feed_rss(url, 3)
        elif tipo == 'json':
            noticias = processar_json_noticias(url, 3)
        else:
            return jsonify({'sucesso': False, 'erro': 'Tipo de feed não suportado'}), 400
        
        return jsonify({'sucesso': True, 'noticias': noticias})
    except Exception as e:
        return jsonify({'sucesso': False, 'erro': str(e)}), 500

# ==============================================================================
# BLOCO 5: ROTAS DE STATUS E HEALTH CHECK
# ==============================================================================
@app.route('/health')
def health_check():
    """Endpoint simples para verificar se a aplicação está rodando"""
    return jsonify({
        "status": "healthy", 
        "service": "social_automation",
        "timestamp": datetime.now().isoformat()
    }), 200

@app.route('/api/status')
def api_status():
    """Endpoint mais detalhado para verificar o status da API"""
    client_count = len(configuracoes) if 'configuracoes' in globals() else 0
    return jsonify({
        "status": "online",
        "service": "Sistema de Automação de Mídias Sociais",
        "version": "2.3",
        "timestamp": datetime.now().isoformat(),
        "client_count": client_count,
        "environment": "production"
    }), 200

# ==============================================================================
# BLOCO 6: INICIALIZAÇÃO
# ==============================================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=True)
