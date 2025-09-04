import os
import json
import uuid
from flask import (Flask, request, jsonify, render_template, session,
                   redirect, url_for, flash)
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import DictCursor
import cloudinary
import cloudinary.uploader

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()

app = Flask(__name__)
# A SECRET_KEY é essencial. Certifique-se de que está configurada no Render.
app.secret_key = os.getenv('SECRET_KEY', 'chave-super-secreta-para-teste-local')

# Configuração do Cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

# --- FUNÇÕES DE BANCO DE DADOS ---

def get_db_connection():
    """Cria e retorna uma nova conexão com o banco de dados."""
    conn_string = os.getenv('DATABASE_URL')
    if not conn_string:
        raise ValueError("ERRO CRÍTICO: A variável de ambiente DATABASE_URL não foi definida!")
    return psycopg2.connect(conn_string)

def init_db():
    """Inicializa o banco de dados e cria as tabelas se não existirem."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS clientes (
                    id TEXT PRIMARY KEY,
                    nome TEXT NOT NULL UNIQUE,
                    config JSONB,
                    data_criacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS feeds (
                    id SERIAL PRIMARY KEY,
                    cliente_id TEXT NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
                    nome TEXT NOT NULL,
                    url TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    categoria TEXT
                )
            ''')
        conn.commit()
        print("✅ Tabelas do banco de dados verificadas/criadas.")
    except psycopg2.Error as e:
        print(f"❌ Erro ao inicializar o DB: {e}")
    finally:
        conn.close()

# --- ROTAS PRINCIPAIS ---

@app.route('/')
def dashboard():
    if 'cliente_id' not in session:
        return redirect(url_for('login'))
    
    cliente_id = session['cliente_id']
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT nome, config FROM clientes WHERE id = %s", (cliente_id,))
            cliente = cur.fetchone()

        if not cliente:
            session.clear()
            flash("Cliente não encontrado. Por favor, faça login novamente.", "warning")
            return redirect(url_for('login'))

        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM feeds WHERE cliente_id = %s ORDER BY nome", (cliente_id,))
            feeds = cur.fetchall()
        
        config_cliente = cliente['config'] or {}
        # Uma verificação mais robusta da configuração
        config_completa = all(config_cliente.get(k) for k in ['logo_url', 'font_url_titulo'])

    except psycopg2.Error as e:
        flash(f"Erro de banco de dados ao carregar o dashboard: {e}", "danger")
        return redirect(url_for('login'))
    finally:
        conn.close()
    
    return render_template('dashboard.html', config=config_cliente, feeds=feeds, config_completa=config_completa)

@app.route('/login', methods=['GET', 'POST'])
def login():
    # SOLUÇÃO DEFINITIVA: Limpa a sessão sempre que a página de login é acessada
    session.clear()

    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        if not cliente_id:
            flash("É necessário selecionar um cliente.", "warning")
            return redirect(url_for('login'))
        
        # Verifica se o cliente realmente existe antes de criar a sessão
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM clientes WHERE id = %s", (cliente_id,))
                if cur.fetchone():
                    session['cliente_id'] = cliente_id
                    return redirect(url_for('dashboard'))
                else:
                    flash("Cliente selecionado não é válido.", "danger")
        finally:
            conn.close()

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('SELECT id, nome FROM clientes ORDER BY nome')
            clientes = cur.fetchall()
    except psycopg2.Error as e:
        flash(f"Não foi possível carregar a lista de clientes: {e}", "danger")
        clientes = []
    finally:
        conn.close()

    return render_template('login.html', clientes=clientes)

@app.route('/logout')
def logout():
    session.clear()
    flash("Você saiu da sua conta.", "info")
    return redirect(url_for('login'))

# --- ROTAS DE GERENCIAMENTO ---

@app.route('/adicionar-cliente', methods=['GET', 'POST'])
def adicionar_cliente():
    if request.method == 'POST':
        nome_cliente = request.form.get('nome_cliente', '').strip()
        if not nome_cliente:
            flash("O nome do cliente não pode ser vazio.", "danger")
            return render_template('adicionar_cliente.html')

        novo_id = f"cliente_{uuid.uuid4().hex[:8]}"
        config_inicial = {'nome': nome_cliente}
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO clientes (id, nome, config) VALUES (%s, %s, %s)",
                            (novo_id, nome_cliente, json.dumps(config_inicial)))
            conn.commit()
            flash(f"Cliente '{nome_cliente}' criado com sucesso! Faça o login.", "success")
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            flash(f"Já existe um cliente com o nome '{nome_cliente}'.", "danger")
            return render_template('adicionar_cliente.html')
        except psycopg2.Error as e:
            flash(f"Erro de banco de dados: {e}", "danger")
            return render_template('adicionar_cliente.html')
        finally:
            conn.close()
        
    return render_template('adicionar_cliente.html')

@app.route('/api/adicionar-feed', methods=['POST'])
def api_adicionar_feed():
    if 'cliente_id' not in session:
        return jsonify(sucesso=False, erro='Sessão expirada. Faça login novamente.'), 401
    
    cliente_id = session['cliente_id']
    dados = request.form
    
    nome, url, tipo = dados.get('nome'), dados.get('url'), dados.get('tipo')
    if not all([nome, url, tipo]):
        return jsonify(sucesso=False, erro='Nome, URL e Tipo são obrigatórios.'), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feeds (cliente_id, nome, url, tipo, categoria) VALUES (%s, %s, %s, %s, %s)",
                (cliente_id, nome, url, tipo, dados.get('categoria'))
            )
        conn.commit()
        return jsonify(sucesso=True, mensagem='Feed adicionado com sucesso!')
    except psycopg2.Error as e:
        return jsonify(sucesso=False, erro=f'Erro de banco de dados: {e}'), 500
    finally:
        conn.close()

@app.route('/api/remover-feed/<int:feed_id>', methods=['POST'])
def api_remover_feed(feed_id):
    if 'cliente_id' not in session:
        return jsonify(sucesso=False, erro='Sessão expirada.'), 401

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM feeds WHERE id = %s AND cliente_id = %s", (feed_id, session['cliente_id']))
        conn.commit()
        if cur.rowcount > 0:
            return jsonify(sucesso=True, mensagem='Feed removido!')
        else:
            return jsonify(sucesso=False, erro='Feed não encontrado ou não pertence a você.'), 404
    except psycopg2.Error as e:
        return jsonify(sucesso=False, erro=f'Erro de banco de dados: {e}'), 500
    finally:
        conn.close()


# --- INICIALIZAÇÃO ---

def initialize_app():
    """Função para ser chamada no comando de build do Render."""
    print("🚀 Executando inicialização da aplicação...")
    init_db()

if __name__ == '__main__':
    initialize_app()
    port = int(os.environ.get('PORT', 5000))
    # Para testes locais, debug=True é útil. No Render, ele desliga sozinho.
    app.run(host='0.0.0.0', port=port, debug=True)
