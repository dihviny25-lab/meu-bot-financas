# main.py
import logging
import os
import shlex
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import FastAPI
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes
import uvicorn

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))


def normalize_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


DATABASE_URL = normalize_db_url(os.getenv("DATABASE_URL", "").strip())
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Defina TELEGRAM_BOT_TOKEN")
if not DATABASE_URL:
    raise RuntimeError("Defina DATABASE_URL")

engine = create_async_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

CATEGORIAS_DESPESA = {
    "alimentacao": ["almoço", "janta", "pizza", "mercado", "feira", "restaurante", "lanche", "ifood", "comida", "café", "açaí", "salgado", "padaria", "hambúrguer", "sushi", "marmita", "quentinha", "supermercado", "hortifruti", "açougue", "sorvete", "doce", "bebida"],
    "transporte": ["uber", "99", "táxi", "ônibus", "metrô", "combustível", "gasolina", "estacionamento", "pedágio", "manutenção carro", "revisão", "ipva", "seguro auto", "bicicleta", "transporte público"],
    "moradia": ["aluguel", "condomínio", "luz", "energia", "água", "gás", "internet", "iptu", "manutenção", "material", "faxineira", "reforma"],
    "lazer": ["cinema", "teatro", "show", "netflix", "spotify", "game", "playstation", "streaming", "bar", "cerveja", "balada", "festa", "parque", "viagem", "hotel"],
    "saude": ["farmácia", "médico", "dentista", "exame", "plano de saúde", "academia", "personal", "terapia", "psicólogo", "remédio"],
    "educacao": ["curso", "livro", "faculdade", "material escolar", "inglês", "espanhol", "idioma", "pós-graduação", "workshop"],
    "roupas": ["camisa", "calça", "tênis", "sapato", "loja", "shopping", "vestido", "blusa", "jaqueta", "bermuda"],
    "pet": ["ração", "veterinário", "pet shop", "banho", "tosa"],
    "impostos": ["irpf", "iptu", "imposto de renda", "darf", "taxa"],
    "doacoes": ["igreja", "doação", "caridade", "vaquinha"],
    "outros_despesas": [],
}
CATEGORIAS_RECEITA = {
    "salario": ["salário", "ordenado", "holerite", "remuneração", "vencimento", "13º", "décimo terceiro", "férias"],
    "freelance": ["freela", "bico", "consultoria", "autônomo", "projeto", "serviço prestado"],
    "investimentos": ["dividendo", "jcp", "aluguel de ação", "rendimento", "resgate", "venda de ativo"],
    "presente": ["presente", "aniversário", "natal", "amigo secreto"],
    "reembolso": ["reembolso", "estorno", "devolução", "restituição"],
    "bonus": ["bônus", "plr", "participação nos lucros", "comissão"],
    "vendas": ["venda", "olx", "marketplace", "desapego", "usado"],
    "renda_extra": ["cashback", "programa de fidelidade", "milhas", "recompensa"],
    "outros_receitas": [],
}


def norm(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


class Base(DeclarativeBase):
    pass


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(100))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(Integer, index=True)
    type: Mapped[str] = mapped_column(String(20), index=True)  # receita | despesa
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    category: Mapped[str] = mapped_column(String(100))
    card_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cards.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    card: Mapped[Optional[Card]] = relationship("Card")


def classify(description: str, mapping: dict[str, list[str]], fallback: str) -> str:
    text = norm(description)
    for category, keywords in mapping.items():
        for keyword in keywords:
            if norm(keyword) in text:
                return category
    return fallback


def parse_amount(raw: str) -> Decimal:
    raw = raw.strip().replace("R$", "").replace(".", "").replace(",", ".")
    value = Decimal(raw)
    if value <= 0:
        raise ValueError("valor deve ser positivo")
    return value.quantize(Decimal("0.01"))


def money(value: Decimal | float | int | None) -> str:
    value = Decimal(value or 0).quantize(Decimal("0.01"))
    txt = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {txt}"


def parse_expense_args(text: str) -> tuple[str, Decimal, Optional[str]]:
    rest = text.partition(" ")[2].strip()
    parts = shlex.split(rest)
    card_name = None

    if "--cartao" in parts:
        idx = parts.index("--cartao")
        card_name = " ".join(parts[idx + 1:]).strip()
        parts = parts[:idx]
        if not card_name:
            raise ValueError("informe o nome do cartão após --cartao")

    if len(parts) < 2:
        raise ValueError("uso: /despesa <descrição> <valor> [--cartao Nome]")

    amount = parse_amount(parts[-1])
    description = " ".join(parts[:-1]).strip()
    if not description:
        raise ValueError("descrição inválida")
    return description, amount, card_name


def parse_income_args(text: str) -> tuple[str, Decimal]:
    rest = text.partition(" ")[2].strip()
    parts = shlex.split(rest)

    if len(parts) < 2:
        raise ValueError("uso: /receita <descrição> <valor>")

    amount = parse_amount(parts[-1])
    description = " ".join(parts[:-1]).strip()
    if not description:
        raise ValueError("descrição inválida")
    return description, amount


async def get_default_card(session: AsyncSession, chat_id: int) -> Card:
    result = await session.execute(
        select(Card).where(Card.chat_id == chat_id, Card.is_default.is_(True))
    )
    card = result.scalar_one_or_none()
    if card:
        return card

    card = Card(chat_id=chat_id, name="Principal", is_default=True)
    session.add(card)
    await session.commit()
    await session.refresh(card)
    return card


async def get_card_by_name(session: AsyncSession, chat_id: int, name: str) -> Optional[Card]:
    result = await session.execute(
        select(Card).where(Card.chat_id == chat_id, func.lower(Card.name) == name.lower())
    )
    return result.scalar_one_or_none()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    async with SessionLocal() as session:
        await get_default_card(session, chat_id)

    text = (
        "Bot financeiro ativo.\n\n"
        "Comandos:\n"
        "/start\n/help\n"
        "/despesa <descrição> <valor> [--cartao Nome]\n"
        "/receita <descrição> <valor>\n"
        "/saldo\n/extrato\n/apagar <id>\n"
        "/relatorio [semanal|quinzenal|mensal]\n"
        "/estatisticas\n/resumo_categorias\n"
        "/cartoes\n/adicionar_cartao <nome>\n/set_cartao_padrao <nome>"
    )
    await update.message.reply_text(text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Exemplos:\n"
        '/despesa "mercado atacadao" 250,90\n'
        '/despesa "pizza sexta" 59.90 --cartao Nubank\n'
        '/receita "salário maio" 4500\n'
        "/relatorio mensal\n"
        "/apagar 12\n\n"
        "Regras:\n"
        "- despesas e receitas recebem categoria automática\n"
        "- se /despesa não informar cartão, o padrão é usado\n"
        "- o ID da transação aparece no /extrato"
    )
    await update.message.reply_text(text)


async def cmd_despesa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    try:
        description, amount, card_name = parse_expense_args(update.message.text)
    except (ValueError, InvalidOperation) as e:
        await update.message.reply_text(str(e))
        return

    category = classify(description, CATEGORIAS_DESPESA, "outros_despesas")

    async with SessionLocal() as session:
        if card_name:
            card = await get_card_by_name(session, chat_id, card_name)
            if not card:
                await update.message.reply_text(f'Cartão "{card_name}" não encontrado.')
                return
        else:
            card = await get_default_card(session, chat_id)

        tx = Transaction(
            chat_id=chat_id,
            type="despesa",
            description=description,
            amount=amount,
            category=category,
            card_id=card.id,
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)

    await update.message.reply_text(
        f"Despesa registrada.\nID: {tx.id}\nDescrição: {description}\nValor: {money(amount)}\nCategoria: {category}\nCartão: {card.name}"
    )


async def cmd_receita(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    try:
        description, amount = parse_income_args(update.message.text)
    except (ValueError, InvalidOperation) as e:
        await update.message.reply_text(str(e))
        return

    category = classify(description, CATEGORIAS_RECEITA, "outros_receitas")

    async with SessionLocal() as session:
        tx = Transaction(
            chat_id=chat_id,
            type="receita",
            description=description,
            amount=amount,
            category=category,
            card_id=None,
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)

    await update.message.reply_text(
        f"Receita registrada.\nID: {tx.id}\nDescrição: {description}\nValor: {money(amount)}\nCategoria: {category}"
    )


async def cmd_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    async with SessionLocal() as session:
        receitas = (
            await session.execute(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.chat_id == chat_id, Transaction.type == "receita"
                )
            )
        ).scalar_one()

        despesas = (
            await session.execute(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.chat_id == chat_id, Transaction.type == "despesa"
                )
            )
        ).scalar_one()

        cards_result = await session.execute(
            select(Card.name, func.coalesce(func.sum(Transaction.amount), 0))
            .select_from(Card)
            .outerjoin(Transaction, Transaction.card_id == Card.id)
            .where(Card.chat_id == chat_id)
            .group_by(Card.id, Card.name)
            .order_by(Card.name)
        )
        cards = cards_result.all()

    saldo = Decimal(receitas) - Decimal(despesas)
    lines = [
        f"Receitas: {money(receitas)}",
        f"Despesas: {money(despesas)}",
        f"Saldo: {money(saldo)}",
        "",
        "Gastos por cartão:",
    ]
    if cards:
        for name, total in cards:
            lines.append(f"- {name}: {money(total)}")
    else:
        lines.append("- nenhum cartão cadastrado")

    await update.message.reply_text("\n".join(lines))


async def cmd_extrato(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    async with SessionLocal() as session:
        result = await session.execute(
            select(Transaction, Card.name)
            .outerjoin(Card, Card.id == Transaction.card_id)
            .where(Transaction.chat_id == chat_id)
            .order_by(Transaction.created_at.desc(), Transaction.id.desc())
            .limit(10)
        )
        rows = result.all()

    if not rows:
        await update.message.reply_text("Nenhuma transação encontrada.")
        return

    lines = ["Últimas 10 transações:"]
    for tx, card_name in rows:
        base = (
            f"ID {tx.id} | {tx.created_at.strftime('%d/%m %H:%M')} | "
            f"{tx.type} | {tx.description} | {money(tx.amount)} | {tx.category}"
        )
        if tx.type == "despesa" and card_name:
            base += f" | cartão: {card_name}"
        lines.append(base)

    await update.message.reply_text("\n".join(lines))


async def cmd_apagar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Uso: /apagar <id>")
        return

    try:
        tx_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID inválido.")
        return

    async with SessionLocal() as session:
        result = await session.execute(
            select(Transaction).where(Transaction.id == tx_id, Transaction.chat_id == chat_id)
        )
        tx = result.scalar_one_or_none()
        if not tx:
            await update.message.reply_text("Transação não encontrada.")
            return

        await session.delete(tx)
        await session.commit()

    await update.message.reply_text(f"Transação {tx_id} apagada.")


async def cmd_relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    periodo = (context.args[0].lower() if context.args else "mensal")
    dias = {"semanal": 7, "quinzenal": 15, "mensal": 30}.get(periodo, 30)
    inicio = datetime.utcnow() - timedelta(days=dias)

    async with SessionLocal() as session:
        receitas = (
            await session.execute(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.chat_id == chat_id,
                    Transaction.type == "receita",
                    Transaction.created_at >= inicio,
                )
            )
        ).scalar_one()

        despesas = (
            await session.execute(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.chat_id == chat_id,
                    Transaction.type == "despesa",
                    Transaction.created_at >= inicio,
                )
            )
        ).scalar_one()

    saldo = Decimal(receitas) - Decimal(despesas)
    await update.message.reply_text(
        f"Relatório {periodo} ({dias} dias)\n"
        f"Receitas: {money(receitas)}\n"
        f"Despesas: {money(despesas)}\n"
        f"Saldo: {money(saldo)}"
    )


async def cmd_estatisticas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    async with SessionLocal() as session:
        stats = (
            await session.execute(
                select(
                    func.coalesce(func.avg(Transaction.amount), 0),
                    func.coalesce(func.max(Transaction.amount), 0),
                    func.count(Transaction.id),
                ).where(Transaction.chat_id == chat_id, Transaction.type == "despesa")
            )
        ).one()

        top_category = (
            await session.execute(
                select(Transaction.category, func.sum(Transaction.amount).label("total"))
                .where(Transaction.chat_id == chat_id, Transaction.type == "despesa")
                .group_by(Transaction.category)
                .order_by(func.sum(Transaction.amount).desc())
                .limit(1)
            )
        ).first()

    avg_value, max_value, count_tx = stats
    if int(count_tx or 0) == 0:
        await update.message.reply_text("Nenhuma despesa para calcular estatísticas.")
        return

    categoria = top_category[0] if top_category else "-"
    total_categoria = top_category[1] if top_category else 0
    await update.message.reply_text(
        f"Média por gasto: {money(avg_value)}\n"
        f"Maior gasto: {money(max_value)}\n"
        f"Categoria que mais gasta: {categoria} ({money(total_categoria)})"
    )


async def cmd_resumo_categorias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Transaction.category, func.sum(Transaction.amount).label("total"))
                .where(Transaction.chat_id == chat_id, Transaction.type == "despesa")
                .group_by(Transaction.category)
                .order_by(func.sum(Transaction.amount).desc())
            )
        ).all()

    if not rows:
        await update.message.reply_text("Nenhuma despesa encontrada.")
        return

    grand_total = sum(Decimal(total) for _, total in rows)
    lines = ["Resumo por categorias:"]
    for category, total in rows:
        pct = (Decimal(total) / grand_total * 100) if grand_total else Decimal("0")
        lines.append(f"- {category}: {money(total)} ({pct:.1f}%)")

    await update.message.reply_text("\n".join(lines))


async def cmd_cartoes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Card).where(Card.chat_id == chat_id).order_by(Card.is_default.desc(), Card.name.asc())
            )
        ).scalars().all()

    if not rows:
        await update.message.reply_text("Nenhum cartão cadastrado.")
        return

    lines = ["Cartões cadastrados:"]
    for card in rows:
        marker = " (padrão)" if card.is_default else ""
        lines.append(f"- {card.name}{marker}")
    await update.message.reply_text("\n".join(lines))


async def cmd_adicionar_cartao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("Uso: /adicionar_cartao <nome>")
        return

    async with SessionLocal() as session:
        existing = await get_card_by_name(session, chat_id, name)
        if existing:
            await update.message.reply_text("Esse cartão já existe.")
            return

        card = Card(chat_id=chat_id, name=name, is_default=False)
        session.add(card)
        await session.commit()

    await update.message.reply_text(f'Cartão "{name}" adicionado.')


async def cmd_set_cartao_padrao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("Uso: /set_cartao_padrao <nome>")
        return

    async with SessionLocal() as session:
        target = await get_card_by_name(session, chat_id, name)
        if not target:
            await update.message.reply_text("Cartão não encontrado.")
            return

        current_defaults = (
            await session.execute(select(Card).where(Card.chat_id == chat_id, Card.is_default.is_(True)))
        ).scalars().all()

        for card in current_defaults:
            card.is_default = False
        target.is_default = True

        await session.commit()

    await update.message.reply_text(f'Cartão padrão definido: "{name}".')


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def build_bot() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("despesa", cmd_despesa))
    app.add_handler(CommandHandler("receita", cmd_receita))
    app.add_handler(CommandHandler("saldo", cmd_saldo))
    app.add_handler(CommandHandler("extrato", cmd_extrato))
    app.add_handler(CommandHandler("apagar", cmd_apagar))
    app.add_handler(CommandHandler("relatorio", cmd_relatorio))
    app.add_handler(CommandHandler("estatisticas", cmd_estatisticas))
    app.add_handler(CommandHandler("resumo_categorias", cmd_resumo_categorias))
    app.add_handler(CommandHandler("cartoes", cmd_cartoes))
    app.add_handler(CommandHandler("adicionar_cartao", cmd_adicionar_cartao))
    app.add_handler(CommandHandler("set_cartao_padrao", cmd_set_cartao_padrao))
    return app


telegram_app: Optional[Application] = None
web_app = FastAPI(title="finance-bot")


@web_app.get("/")
async def root():
    return {"status": "ok", "service": "finance-bot"}


@web_app.get("/health")
async def health():
    return {"status": "healthy", "time": datetime.utcnow().isoformat()}


@web_app.on_event("startup")
async def on_startup():
    global telegram_app
    await init_db()
    telegram_app = build_bot()
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot iniciado com polling.")


@web_app.on_event("shutdown")
async def on_shutdown():
    global telegram_app
    if telegram_app:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
        logger.info("Bot finalizado.")


if __name__ == "__main__":
    uvicorn.run("bot:web_app", host="0.0.0.0", port=PORT, reload=False)