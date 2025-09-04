@app.route('/')
def dashboard():
    if 'cliente_id' not in session:
        return redirect(url_for('login'))
    
    cliente_id = session['cliente_id']
    conn = get_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT nome, config FROM clientes WHERE id = %s", (cliente_id,))
        cliente = cur.fetchone()

    # --- INÍCIO DA CORREÇÃO MÁGICA ---
    # Se não encontrou o cliente (porque a sessão é antiga/inválida)...
    if not cliente:
        # ...limpa a sessão e manda o usuário de volta para o login.
        session.clear()
        flash("Sua sessão era inválida ou expirou. Por favor, faça login novamente.", "warning")
        conn.close() # Fecha a conexão antes de redirecionar
        return redirect(url_for('login'))
    # --- FIM DA CORREÇÃO MÁGICA ---

    # Se o cliente foi encontrado, o código continua normalmente.
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM feeds WHERE cliente_id = %s", (cliente_id,))
        feeds = cur.fetchall()
    conn.close()
    
    config_completa = cliente['config'] and cliente['config'].get('logo_url') and cliente['config'].get('font_url_titulo')
    
    return render_template('dashboard.html', config=cliente['config'], cliente_id=cliente_id, 
                           feeds=feeds, config_completa=config_completa)
