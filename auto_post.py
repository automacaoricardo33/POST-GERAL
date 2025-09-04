import os
import json
import feedparser
import requests
import uuid
from time import sleep
from dotenv import load_dotenv
from app import get_db_connection, gerar_imagem_noticia # Importa funções do app.py
import cloudinary
import cloudinary.uploader
import psycopg2
from psycopg2.extras import DictCursor

# Carrega variáveis de ambiente
load_dotenv()

# Configuração do Cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

# Arquivo para armazenar links já postados (para fins de backup local)
# A fonte da verdade será o banco de dados
POSTED_LOG_FILE = 'posted_links.log' 

def carregar_links_postados_db(conn):
    """Carrega links postados a partir de uma tabela no DB."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS links_postados (
                id SERIAL PRIMARY KEY,
                link TEXT NOT NULL UNIQUE,
                data_postagem TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("SELECT link FROM links_postados")
        links = {row[0] for row in cur.fetchall()}
    conn.commit()
    return links

def salvar_link_postado_db(conn, link):
    """Salva um novo link no banco de dados."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO links_postados (link) VALUES (%s) ON CONFLICT (link) DO NOTHING", (link,))
    conn.commit()

def verificar_configuracao_completa(config):
    """Verifica se a configuração essencial do cliente foi preenchida."""
    essenciais = ['nome', 'logo_url', 'font_url_titulo', 'font_url_texto']
    return all(key in config and config[key] for key in essenciais)

def processar_feed_rss(feed_url, links_postados):
    """Busca e processa notícias de um feed RSS."""
    print(f"  Processando RSS: {feed_url}")
    try:
        noticias = feedparser.parse(feed_url)
        if noticias.bozo:
            print(f"    AVISO: Erro ao parsear o feed. Pode estar mal formatado. {noticias.bozo_exception}")
            return []

        novos_posts = []
        for entry in noticias.entries:
            link = entry.get('link')
            titulo = entry.get('title')
            texto = entry.get('summary') or entry.get('description', '')

            if not all([link, titulo, texto]):
                continue

            if link not in links_postados:
                novos_posts.append({'titulo': titulo, 'texto': texto, 'link': link})
        
        return novos_posts
        
    except Exception as e:
        print(f"    ERRO: Falha ao buscar ou processar feed RSS {feed_url}. Erro: {e}")
        return []

def processar_feed_json(feed_url, links_postados):
    """Busca e processa notícias de um feed JSON."""
    print(f"  Processando JSON: {feed_url}")
    try:
        response = requests.get(feed_url, timeout=10)
        response.raise_for_status()
        noticias = response.json()

        novos_posts = []
        items = noticias.get('items') or noticias.get('articles') or noticias

        if not isinstance(items, list):
            print("    ERRO: O JSON não contém uma lista de notícias.")
            return []

        for item in items:
            link = item.get('link') or item.get('url')
            titulo = item.get('title')
            texto = item.get('summary') or item.get('description') or item.get('content', '')

            if not all([link, titulo, texto]):
                continue

            if link not in links_postados:
                novos_posts.append({'titulo': titulo, 'texto': texto, 'link': link})
        
        return novos_posts

    except requests.RequestException as e:
        print(f"    ERRO: Falha ao buscar feed JSON {feed_url}. Erro: {e}")
        return []
    except json.JSONDecodeError:
        print(f"    ERRO: O conteúdo de {feed_url} não é um JSON válido.")
        return []
    except Exception as e:
        print(f"    ERRO: Ocorreu um erro inesperado ao processar o JSON. Erro: {e}")
        return []


def iniciar_automacao():
    """Função principal que roda o robô de postagem."""
    print("🤖 Iniciando robô de postagem automática...")
    
    conn = None
    try:
        conn = get_db_connection()
        links_postados = carregar_links_postados_db(conn)
        print(f"Carregados {len(links_postados)} links já postados do banco de dados.")

        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('SELECT id, config FROM clientes')
            clientes = cur.fetchall()
        
        if not clientes:
            print("Nenhum cliente encontrado no banco de dados. Encerrando.")
            return

        for cliente in clientes:
            cliente_id = cliente['id']
            config_cliente = cliente['config'] or {}
                
            nome_cliente = config_cliente.get('nome', cliente_id)
            print(f"\n➡️  Verificando cliente: {nome_cliente}")

            if not verificar_configuracao_completa(config_cliente):
                print("  Configuração do cliente está incompleta (faltam logo, fontes, etc). Pulando.")
                continue

            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute('SELECT * FROM feeds WHERE cliente_id = %s', (cliente_id,))
                feeds = cur.fetchall()
            
            if not feeds:
                print("  Nenhum feed RSS/JSON cadastrado para este cliente.")
                continue

            for feed in feeds:
                posts_para_gerar = []
                if feed['tipo'] == 'rss':
                    posts_para_gerar = processar_feed_rss(feed['url'], links_postados)
                elif feed['tipo'] == 'json':
                    posts_para_gerar = processar_feed_json(feed['url'], links_postados)

                if not posts_para_gerar:
                    print(f"    Nenhuma notícia nova encontrada em {feed['url']}.")
                    continue

                print(f"    ✅ Encontradas {len(posts_para_gerar)} notícias novas!")
                
                for post in reversed(posts_para_gerar):
                    try:
                        print(f"      Gerando imagem para: '{post['titulo'][:50]}...'")
                        
                        imagem = gerar_imagem_noticia(post['titulo'], post['texto'], config_cliente)
                        
                        # Salva a imagem em memória para enviar ao Cloudinary
                        img_byte_arr = io.BytesIO()
                        imagem.save(img_byte_arr, format='PNG')
                        img_byte_arr.seek(0)

                        # Envia para o Cloudinary
                        upload_result = cloudinary.uploader.upload(
                            img_byte_arr,
                            folder=f"automacao/{cliente_id}/posts_gerados",
                            public_id=f"post_{uuid.uuid4().hex[:12]}"
                        )
                        
                        image_url = upload_result.get('secure_url')
                        print(f"      ✅ Imagem enviada para o Cloudinary: {image_url}")
                        
                        # TODO: Adicionar aqui a lógica para postar a `image_url` nas redes sociais
                        
                        salvar_link_postado_db(conn, post['link'])
                        links_postados.add(post['link'])
                        
                        sleep(2)

                    except Exception as e:
                        print(f"      ❌ ERRO CRÍTICO ao gerar ou enviar imagem para '{post['titulo']}'. Erro: {e}")
                        break
    
    except (psycopg2.Error, ValueError) as e:
        print(f"ERRO DE BANCO DE DADOS: {e}")
    finally:
        if conn:
            conn.close()
        print("\n🏁 Robô finalizou a verificação.")


if __name__ == '__main__':
    iniciar_automacao()
