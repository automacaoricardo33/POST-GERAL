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
# É MUITO IMPORTANTE que você defina a variável 'SECRET_KEY' nas configurações do Render
app.secret_key = os.getenv('SECRET_KEY', 'uma-chave-secreta-muito-forte-para-desenvolvimento')

# Configuração do Cloudinary a partir das variáveis de ambiente
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

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
        # Tabela de feeds atualizada para incluir nome e categoria
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
    conn.close()
    print("✅ Tabelas do banco de dados verificadas/criadas com sucesso.")

# --- ROTAS DA APLICAÇÃO ---

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
            flash("Sua sessão era inválida ou o cliente não foi encontrado. Faça login novamente.", "warning")
            conn.close()
            return redirect(url_for('login'))

        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM feeds WHERE cliente_id = %s ORDER BY id", (cliente_id,))
            feeds = cur.fetchall()
        
        config = cliente['config'] or {}
        config_completa = config and config.get('logo_url') and config.get('font_url_titulo')
    
    except psycopg2.Error as e:
        flash(f"Erro ao conectar com o banco de dados: {e}", "danger")
        feeds = []
        config = {}
        config_completa = False
    finally:
        if conn:
            conn.close()

    return render_template('dashboard.html', config=config, cliente_id=cliente_id, 
                           feeds=feeds, config_completa=config_completa)

@app.route('/login', methods=['GET', 'POST'])
def login():
    # CORREÇÃO: Limpa a sessão antiga para sempre mostrar a tela de seleção
    session.clear()

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

            config_atual['nome'] = request.form.get('nome_cliente')
            
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
                           'posicao_logo_x', 'posicao_logo_y', 'tamanho_logo']
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

@app.route('/adicionar-feed', methods=['POST'])
def adicionar_feed():
    if 'cliente_id' not in session:
        return jsonify(sucesso=False, erro='Não autenticado'), 401
    
    cliente_id = session['cliente_id']
    
    # CORREÇÃO: Usando os nomes corretos do formulário
    nome_feed = request.form.get('nome')
    url_feed = request.form.get('url')
    tipo_feed = request.form.get('tipo')
    categoria_feed = request.form.get('categoria')

    if not all([nome_feed, url_feed, tipo_feed]):
        return jsonify(sucesso=False, erro='Nome, URL e tipo são obrigatórios'), 400

    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO feeds (cliente_id, nome, url, tipo, categoria) VALUES (%s, %s, %s, %s, %s)",
                    (cliente_id, nome_feed, url_feed, tipo_feed, categoria_feed))
    conn.commit()
    conn.close()
    
    # Retornar uma resposta JSON é crucial para o JavaScript funcionar
    return jsonify(sucesso=True, mensagem="Feed adicionado com sucesso!")


@app.route('/remover-feed/<int:feed_id>', methods=['POST'])
def remover_feed(feed_id):
    if 'cliente_id' not in session:
        return jsonify(sucesso=False, erro='Não autenticado'), 401

    conn = get_db_connection()
    with conn.cursor() as cur:
        # Garante que só o cliente dono do feed pode removê-lo
        cur.execute("DELETE FROM feeds WHERE id = %s AND cliente_id = %s", (feed_id, session['cliente_id']))
    conn.commit()
    conn.close()
    
    return jsonify(sucesso=True, mensagem="Feed removido com sucesso!")


def initialize_app():
    """Função para ser chamada ANTES de iniciar o servidor Gunicorn no Render."""
    print("🚀 Executando inicialização da aplicação...")
    init_db()

if __name__ == '__main__':
    initialize_app()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
