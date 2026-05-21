import os
import csv
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ================= CONFIGURAÇÃO INICIAL =================
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Token não encontrado. Configure o arquivo .env")

ARQUIVO_TRANSACOES = "transacoes.csv"
ARQUIVO_CARTOES = "cartoes.csv"
CARTAO_PADRAO = "Dinheiro"  # padrão inicial

# ================= CATEGORIAS (EXPANDIDAS) =================
CATEGORIAS_DESPESA = {
    "alimentacao": ["almoço", "janta", "pizza", "mercado", "feira", "restaurante", "lanche", "ifood", "comida", "café", "açaí", "salgado", "padaria", "hambúrguer", "sushi", "marmita", "quentinha", "supermercado", "hortifruti", "açougue", "padaria", "sorvete", "doce", "bebida", "refrigerante", "suco", "água"],
    "transporte": ["uber", "99", "táxi", "ônibus", "metrô", "combustível", "gasolina", "estacionamento", "pedágio", "manutenção carro", "revisão", "ipva", "seguro auto", "bicicleta", "lubrificante", "óleo", "pneu", "transporte público", "vtr", "bilhete único"],
    "moradia": ["aluguel", "condomínio", "luz", "energia", "água", "gás", "internet", "iptu", "manutenção", "material", "faxineira", "diarista", "reforma", "encanador", "eletricista", "pintura", "mobília", "móvel", "eletrodoméstico", "decoração", "jardinagem"],
    "lazer": ["cinema", "teatro", "show", "netflix", "spotify", "game", "playstation", "streaming", "bar", "cerveja", "whisky", "balada", "festa", "parque", "piscina", "viagem", "hotel", "passagem aérea", "resort", "camping", "karaoke", "shopping", "presente"],
    "saude": ["farmácia", "médico", "dentista", "exame", "plano de saúde", "academia", "personal", "terapia", "psicólogo", "fisioterapia", "vacina", "remédio", "óculos", "lente", "suplemento", "protetor solar", "vitamina"],
    "educacao": ["curso", "livro", "faculdade", "material escolar", "inglês", "espanhol", "idioma", "pós-graduação", "mestrado", "workshop", "palestra", "e-book", "audiolivro", "assinatura de curso", "plataforma", "alura", "udemy"],
    "roupas": ["camisa", "calça", "tênis", "sapato", "loja", "shopping", "vestido", "blusa", "jaqueta", "bermuda", "short", "meia", "cueca", "sutiã", "roupa íntima", "acessório", "bolsa", "mochila", "óculos de sol", "relógio"],
    "contas": ["fat cartão", "cartão de crédito", "boleto", "financiamento", "empréstimo", "juros", "multa", "tarifa bancária", "anuidade", "seguro de vida", "consórcio"],
    "pet": ["ração", "veterinário", "pet shop", "banho", "tosa", "brinquedo para cão", "coleira", "vacina pet", "medicamento pet", "adestramento"],
    "impostos": ["irpf", "imposto de renda", "darf", "gps", "iss", "icms", "taxa", "licenciamento"],
    "trabalho": ["material de escritório", "assinatura de software", "cafezinho no trabalho", "estacionamento no trabalho", "uniforme", "ferramenta de trabalho"],
    "doacoes": ["igreja", "templo", "caridade", "vaquinha", "ajuda", "doação", "mesada para filho"],
    "outros_despesas": []
}

CATEGORIAS_RECEITA = {
    "salario": ["salário", "ordenado", "holerite", "remuneração", "vencimento", "13º", "décimo terceiro", "férias", "adicional"],
    "freelance": ["freela", "bico", "consultoria", "autônomo", "projeto", "serviço prestado", "contrato", "hora extra"],
    "investimentos": ["dividendo", "jcp", "aluguel de ação", "rendimento", "resgate", "venda de ativo", "lucro", "day trade", "swing trade", "cdi", "selic", "tesouro direto"],
    "presente": ["presente", "aniversário", "natal", "amigo secreto", "agrado", "mimo"],
    "reembolso": ["reembolso", "estorno", "devolução", "restituição", "imposto devolvido"],
    "bonus": ["bônus", "plr", "participação nos lucros", "comissão", "gratificação", "prêmio"],
    "vendas": ["venda", "olx", "marketplace", "garage sale", "desapego", "usado", "enjoei"],
    "renda_extra": ["cashback", "programa de fidelidade", "milhas", "recompensa", "pesquisa paga", "task", "microtrabalho"],
    "outros_receitas": []
}

# ================= FUNÇÕES AUXILIARES =================
def inicializar_csv():
    # Transações
    if not os.path.exists(ARQUIVO_TRANSACOES):
        with open(ARQUIVO_TRANSACOES, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["data", "descricao", "valor", "tipo", "categoria", "cartao"])
    # Cartões
    if not os.path.exists(ARQUIVO_CARTOES):
        with open(ARQUIVO_CARTOES, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["nome", "padrao"])
            writer.writerow([CARTAO_PADRAO, "sim"])

def carregar_cartoes():
    """Retorna lista de nomes de cartões e o cartão padrão."""
    if not os.path.exists(ARQUIVO_CARTOES):
        inicializar_csv()
    cartoes = []
    padrao = CARTAO_PADRAO
    with open(ARQUIVO_CARTOES, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cartoes.append(row["nome"])
            if row.get("padrao") == "sim":
                padrao = row["nome"]
    return cartoes, padrao

def salvar_cartao(nome):
    """Adiciona um novo cartão (não padrão)."""
    cartoes, _ = carregar_cartoes()
    if nome in cartoes:
        return False
    with open(ARQUIVO_CARTOES, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([nome, "nao"])
    return True

def definir_cartao_padrao(nome):
    cartoes, _ = carregar_cartoes()
    if nome not in cartoes:
        return False
    # Atualiza o arquivo: remove o "sim" de todos e coloca no escolhido
    linhas = []
    with open(ARQUIVO_CARTOES, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if row[0] == nome:
                linhas.append([row[0], "sim"])
            else:
                linhas.append([row[0], "nao"])
    with open(ARQUIVO_CARTOES, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(linhas)
    return True

def identificar_categoria(texto, tipo):
    texto_lower = texto.lower()
    if tipo == "despesa":
        for cat, palavras in CATEGORIAS_DESPESA.items():
            for p in palavras:
                if p in texto_lower:
                    return cat
        return "outros_despesas"
    else:  # receita
        for cat, palavras in CATEGORIAS_RECEITA.items():
            for p in palavras:
                if p in texto_lower:
                    return cat
        return "outros_receitas"

def salvar_transacao(descricao, valor, tipo, categoria, cartao):
    with open(ARQUIVO_TRANSACOES, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), descricao, valor, tipo, categoria, cartao])

def obter_saldo_consolidado():
    """Retorna (total_receitas, total_despesas, saldo_por_cartao)"""
    total_receitas = 0.0
    total_despesas = 0.0
    saldo_por_cartao = {}  # cartao -> (receitas, despesas)
    if not os.path.exists(ARQUIVO_TRANSACOES):
        return total_receitas, total_despesas, saldo_por_cartao
    with open(ARQUIVO_TRANSACOES, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            valor = float(row["valor"])
            tipo = row["tipo"]
            cartao = row["cartao"]
            if cartao not in saldo_por_cartao:
                saldo_por_cartao[cartao] = [0.0, 0.0]  # [receitas, despesas]
            if tipo == "receita":
                total_receitas += valor
                saldo_por_cartao[cartao][0] += valor
            else:
                total_despesas += valor
                saldo_por_cartao[cartao][1] += valor
    return total_receitas, total_despesas, saldo_por_cartao

def obter_ultimas_transacoes(n=10):
    if not os.path.exists(ARQUIVO_TRANSACOES):
        return []
    with open(ARQUIVO_TRANSACOES, mode='r', encoding='utf-8') as f:
        reader = list(csv.DictReader(f))
        return reader[-n:]

def obter_resumo_categorias():
    resumo = {}
    if not os.path.exists(ARQUIVO_TRANSACOES):
        return resumo
    with open(ARQUIVO_TRANSACOES, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["tipo"] == "despesa":
                cat = row["categoria"]
                val = float(row["valor"])
                resumo[cat] = resumo.get(cat, 0) + val
    return resumo

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 *Assistente Financeiro Completo*\n\n"
        "Registre despesas com cartões e receitas com categorização automática.\n\n"
        "Comandos principais:\n"
        "/despesa <descrição> <valor> [--cartao Nome] - Registrar gasto\n"
        "/receita <descrição> <valor> - Registrar entrada\n"
        "/adicionar_cartao <nome> - Cadastrar novo cartão\n"
        "/cartoes - Listar cartões\n"
        "/set_cartao_padrao <nome> - Definir cartão padrão\n"
        "/saldo - Ver saldo total e por cartão\n"
        "/extrato - Últimas transações\n"
        "/resumo_categorias - Gastos por categoria\n"
        "/help - Ajuda detalhada",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 *Ajuda Completa*\n\n"
        "*Despesa:* `/despesa almoço 25.50` (usa cartão padrão)\n"
        "*Despesa com cartão específico:* `/despesa uber 15.00 --cartao Nubank`\n"
        "*Receita:* `/receita salário 3000`\n"
        "*Adicionar cartão:* `/adicionar_cartao Itaú`\n"
        "*Ver cartões:* `/cartoes`\n"
        "*Definir padrão:* `/set_cartao_padrao Nubank`\n"
        "*Saldo total e por cartão:* `/saldo`\n"
        "*Extrato (últimas 10):* `/extrato`\n"
        "*Gastos por categoria:* `/resumo_categorias`",
        parse_mode="Markdown"
    )

async def despesa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: `/despesa descrição valor [--cartao Nome]`", parse_mode="Markdown")
        return

    # Processar argumentos: separar --cartao se existir
    args = list(context.args)
    cartao_especifico = None
    if "--cartao" in args:
        idx = args.index("--cartao")
        if idx + 1 < len(args):
            cartao_especifico = args[idx+1]
            # remove os dois elementos da lista
            args = args[:idx] + args[idx+2:]
        else:
            await update.message.reply_text("Após `--cartao` você precisa informar o nome do cartão.")
            return

    if len(args) < 2:
        await update.message.reply_text("Formato: `/despesa almoço 25.50`", parse_mode="Markdown")
        return

    # O último argumento é o valor
    valor_str = args[-1].replace(',', '.')
    descricao = ' '.join(args[:-1])
    try:
        valor = float(valor_str)
    except:
        await update.message.reply_text("Valor inválido. Use ponto ou vírgula (ex: 25.50).")
        return

    # Obter cartão
    cartoes, padrao = carregar_cartoes()
    if cartao_especifico:
        if cartao_especifico not in cartoes:
            await update.message.reply_text(f"Cartão `{cartao_especifico}` não cadastrado. Use `/adicionar_cartao` primeiro.", parse_mode="Markdown")
            return
        cartao_usado = cartao_especifico
    else:
        cartao_usado = padrao

    categoria = identificar_categoria(descricao, "despesa")
    salvar_transacao(descricao, valor, "despesa", categoria, cartao_usado)

    await update.message.reply_text(
        f"✅ Despesa registrada:\n"
        f"📝 {descricao}\n"
        f"💵 R$ {valor:.2f}\n"
        f"📂 Categoria: {categoria}\n"
        f"💳 Cartão: {cartao_usado}"
    )

async def receita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Uso: `/receita descrição valor`\nEx: `/receita salário 5000`", parse_mode="Markdown")
        return

    valor_str = context.args[-1].replace(',', '.')
    descricao = ' '.join(context.args[:-1])
    try:
        valor = float(valor_str)
    except:
        await update.message.reply_text("Valor inválido.")
        return

    categoria = identificar_categoria(descricao, "receita")
    # Receitas não usam cartão; armazenamos " - " no campo cartão
    salvar_transacao(descricao, valor, "receita", categoria, "-")
    await update.message.reply_text(
        f"✅ Receita registrada:\n📝 {descricao}\n💵 R$ {valor:.2f}\n📂 Categoria: {categoria}"
    )

async def adicionar_cartao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: `/adicionar_cartao NomeDoCartao`")
        return
    nome = ' '.join(context.args)
    if salvar_cartao(nome):
        await update.message.reply_text(f"💳 Cartão `{nome}` adicionado com sucesso!", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"Cartão `{nome}` já existe.", parse_mode="Markdown")

async def listar_cartoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cartoes, padrao = carregar_cartoes()
    if not cartoes:
        await update.message.reply_text("Nenhum cartão cadastrado. Use `/adicionar_cartao`.")
        return
    msg = "💳 *Seus cartões:*\n"
    for c in cartoes:
        if c == padrao:
            msg += f"• {c} (padrão)\n"
        else:
            msg += f"• {c}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def set_cartao_padrao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: `/set_cartao_padrao NomeDoCartao`")
        return
    nome = ' '.join(context.args)
    if definir_cartao_padrao(nome):
        await update.message.reply_text(f"✅ Cartão padrão alterado para `{nome}`.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"Cartão `{nome}` não encontrado. Use `/cartoes` para ver os disponíveis.", parse_mode="Markdown")

async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_receitas, total_despesas, saldo_por_cartao = obter_saldo_consolidado()
    saldo_total = total_receitas - total_despesas
    msg = f"📊 *Resumo Financeiro*\n\n"
    msg += f"💰 Receitas totais: R$ {total_receitas:.2f}\n"
    msg += f"💸 Despesas totais: R$ {total_despesas:.2f}\n"
    msg += f"📌 *Saldo geral:* R$ {saldo_total:.2f}\n\n"
    msg += "*Saldo por cartão:*\n"
    if saldo_por_cartao:
        for cartao, (rec, desp) in saldo_por_cartao.items():
            if cartao == "-":
                continue  # receitas sem cartão
            saldo_cartao = rec - desp
            msg += f"• {cartao}: R$ {saldo_cartao:.2f} (receitas R${rec:.2f} / despesas R${desp:.2f})\n"
    else:
        msg += "Nenhuma transação registrada.\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def extrato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transacoes = obter_ultimas_transacoes(10)
    if not transacoes:
        await update.message.reply_text("Nenhuma transação registrada.")
        return
    msg = "📋 *Últimas transações:*\n"
    for t in reversed(transacoes):
        tipo_emoji = "💰" if t["tipo"] == "receita" else "💸"
        cartao_info = f" [{t['cartao']}]" if t["cartao"] != "-" else ""
        msg += f"{tipo_emoji} {t['data'][:10]} {t['descricao']} {cartao_info}: R$ {float(t['valor']):.2f} ({t['categoria']})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def resumo_categorias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    resumo = obter_resumo_categorias()
    if not resumo:
        await update.message.reply_text("Nenhuma despesa registrada.")
        return
    total_gastos = sum(resumo.values())
    msg = "📊 *Gastos por categoria:*\n"
    for cat, valor in sorted(resumo.items(), key=lambda x: x[1], reverse=True):
        msg += f"• {cat}: R$ {valor:.2f}\n"
    msg += f"\n💵 *Total de despesas:* R$ {total_gastos:.2f}"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ================= MAIN =================
def main():
    inicializar_csv()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("despesa", despesa))
    app.add_handler(CommandHandler("receita", receita))
    app.add_handler(CommandHandler("adicionar_cartao", adicionar_cartao))
    app.add_handler(CommandHandler("cartoes", listar_cartoes))
    app.add_handler(CommandHandler("set_cartao_padrao", set_cartao_padrao))
    app.add_handler(CommandHandler("saldo", saldo))
    app.add_handler(CommandHandler("extrato", extrato))
    app.add_handler(CommandHandler("resumo_categorias", resumo_categorias))
    print("Bot financeiro rodando com suporte a cartões e categorias máximas...")
    app.run_polling()

if __name__ == "__main__":
    main()