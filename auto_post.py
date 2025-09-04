import sqlite3
import json
import feedparser
import requests
import os
import uuid
from time import sleep
from app import gerar_imagem_noticia # Importa a função de gerar imagem do seu app

DB_NAME = 'clientes.db'
POSTED_LOG_FILE = 'posted_links.log'
OUTPUT_FOLDER = 'output'

def get_db_connection():
    """Cria uma conexão com o banco de dados."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def carregar_links_postados():
    """Carrega os links que já foram postados para evitar duplicatas."""
    if not os.path.exists(POSTED_LOG_FILE):
        return set()
    with open(POSTED_LOG_FILE, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f)

def salvar_link_postado(link):
    """Salva um novo link no arquivo de log."""
    with open(POSTED_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(link + '\n')

def verificar_configuracao_completa(config):
    """Verifica se a configuração essencial do cliente foi preenchida."""
    essenciais = ['nome', 'logo_path', 'font_path_titulo', 'font_path_texto']
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
            # Tenta encontrar o melhor texto para o resumo
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
        response.raise_for_status() # Lança um erro para status HTTP 4xx/5xx
        noticias = response.json()

        novos_posts = []
        # Assumindo uma estrutura comum de JSON com uma lista de 'items' ou 'articles'
        items = noticias.get('items') or noticias.get('articles') or noticias

        if not isinstance(items, list):
            print("    ERRO: O JSON não contém uma lista de notícias (procurei por 'items' ou 'articles').")
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
    
    links_postados = carregar_links_postados()
    print(f"Carregados {len(links_postados)} links já postados.")
    
    conn = get_db_connection()
    clientes = conn.execute('SELECT id, config FROM clientes').fetchall()
    
    if not clientes:
        print("Nenhum cliente encontrado no banco de dados. Encerrando.")
        return

    for cliente in clientes:
        cliente_id = cliente['id']
        try:
            config_cliente = json.loads(cliente['config'])
        except (TypeError, json.JSONDecodeError):
            print(f"\nAVISO: Cliente '{cliente_id}' não possui configuração válida. Pulando.")
            continue
            
        nome_cliente = config_cliente.get('nome', cliente_id)
        print(f"\n➡️  Verificando cliente: {nome_cliente}")

        if not verificar_configuracao_completa(config_cliente):
            print("  Configuração do cliente está incompleta (faltam logo, fontes, etc). Pulando.")
            continue

        feeds = conn.execute('SELECT * FROM feeds WHERE cliente_id = ?', (cliente_id,)).fetchall()
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
            
            # Criar pasta de saída para o cliente
            pasta_saida_cliente = os.path.join(OUTPUT_FOLDER, cliente_id)
            os.makedirs(pasta_saida_cliente, exist_ok=True)
            
            for post in reversed(posts_para_gerar): # Pega do mais antigo para o mais novo
                try:
                    print(f"      Gerando imagem para: '{post['titulo'][:50]}...'")
                    
                    # Gera a imagem usando a função do app.py
                    imagem = gerar_imagem_noticia(post['titulo'], post['texto'], config_cliente)
                    
                    nome_arquivo = f"{uuid.uuid4().hex[:12]}.png"
                    caminho_arquivo = os.path.join(pasta_saida_cliente, nome_arquivo)
                    
                    imagem.save(caminho_arquivo)
                    print(f"      ✅ Imagem salva em: {caminho_arquivo}")
                    
                    # Se tudo deu certo, salva o link para não postar de novo
                    salvar_link_postado(post['link'])
                    links_postados.add(post['link'])
                    
                    sleep(2) # Pausa para não sobrecarregar

                except Exception as e:
                    print(f"      ❌ ERRO CRÍTICO ao gerar imagem para '{post['titulo']}'. Erro: {e}")
                    print("      Verifique se os caminhos das fontes e do logo estão corretos na configuração.")
                    break # Para de processar este feed se der um erro de imagem
    
    conn.close()
    print("\n🏁 Robô finalizou a verificação.")


if __name__ == '__main__':
    iniciar_automacao()
