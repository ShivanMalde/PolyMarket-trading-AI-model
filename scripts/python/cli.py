import logging
import sys
from os import getenv
from typing import Optional
from ast import literal_eval
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime

import typer
from rich.console import Console
from rich.pretty import pprint

from agents.polymarket.polymarket import Polymarket
from agents.connectors.chroma import PolymarketRAG
from agents.connectors.news import News
from agents.application.trade import Trader
from agents.application.executor import Executor
from agents.application.creator import Creator

# Configure logging
def setup_logging():
    """Configure logging with rotating file handler"""
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Generate log filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"trading_agent_{timestamp}.log"
    
    # Configure RotatingFileHandler
    # Max file size: 5MB, Keep 5 backup files
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5,
        encoding='utf-8'
    )
    
    # Console handler for terminal output
    console_handler = logging.StreamHandler(sys.stdout)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# Initialize logging
setup_logging()

app = typer.Typer(help="Polymarket AI Trading Agent CLI")
console = Console()

# Initialize clients lazily to avoid import-time errors
_polymarket: Optional[Polymarket] = None
_newsapi_client: Optional[News] = None
_polymarket_rag: Optional[PolymarketRAG] = None


def get_polymarket() -> Polymarket:
    global _polymarket
    if _polymarket is None:
        _polymarket = Polymarket()
    return _polymarket


def get_news() -> News:
    global _newsapi_client
    if _newsapi_client is None:
        _newsapi_client = News()
    return _newsapi_client


def get_rag() -> PolymarketRAG:
    global _polymarket_rag
    if _polymarket_rag is None:
        _polymarket_rag = PolymarketRAG()
    return _polymarket_rag
@app.command()
def get_all_markets(limit: int = 5, sort_by: str = "spread") -> None:
    """
    Query Polymarket's markets
    """
    console.print(f"[cyan]Fetching {limit} markets, sorted by {sort_by}[/cyan]")
    pm = get_polymarket()
    markets = pm.get_all_markets()
    markets = pm.filter_markets_for_trading(markets)
    if sort_by == "spread":
        markets = sorted(markets, key=lambda x: x.spread, reverse=True)
    markets = markets[:limit]
    console.print("[green]Markets:[/green]")
    pprint(markets)


@app.command()
def get_trending_markets(limit: int = 10) -> None:
    """
    Get trending markets sorted by 24-hour volume
    """
    console.print(f"[cyan]Fetching {limit} trending markets (sorted by 24h volume)[/cyan]")
    pm = get_polymarket()
    markets = pm.get_trending_markets(limit=limit)
    console.print(f"[green]Found {len(markets)} trending markets:[/green]")
    pprint(markets)


@app.command()
def get_relevant_news(keywords: str) -> None:
    """
    Use NewsAPI to query the internet
    """
    console.print(f"[cyan]Fetching news for keywords: {keywords}[/cyan]")
    news = get_news()
    articles = news.get_articles_for_cli_keywords(keywords)
    console.print(f"[green]Found {len(articles)} articles:[/green]")
    pprint(articles)


@app.command()
def get_all_events(limit: int = 5, sort_by: str = "number_of_markets") -> None:
    """
    Query Polymarket's events
    """
    console.print(f"[cyan]Fetching {limit} events, sorted by {sort_by}[/cyan]")
    pm = get_polymarket()
    events = pm.get_all_events()
    events = pm.filter_events_for_trading(events)
    if sort_by == "number_of_markets":
        events = sorted(events, key=lambda x: len(x.markets.split(",")), reverse=True)
    events = events[:limit]
    console.print(f"[green]Found {len(events)} events:[/green]")
    pprint(events)


@app.command()
def create_local_markets_rag(local_directory: str) -> None:
    """
    Create a local markets database for RAG
    """
    console.print(f"[cyan]Creating local RAG database in {local_directory}[/cyan]")
    rag = get_rag()
    rag.create_local_markets_rag(local_directory=local_directory)
    console.print("[green]RAG database created successfully![/green]")


@app.command()
def query_local_markets_rag(vector_db_directory: str, query: str) -> None:
    """
    RAG over a local database of Polymarket's events
    """
    console.print(f"[cyan]Querying RAG database: {query}[/cyan]")
    rag = get_rag()
    response = rag.query_local_markets_rag(
        local_directory=vector_db_directory, query=query
    )
    console.print("[green]RAG Results:[/green]")
    pprint(response)


@app.command()
def ask_superforecaster(event_title: str, market_question: str, outcome: str) -> None:
    """
    Ask a superforecaster about a trade
    """
    console.print(f"[cyan]Event: {event_title}[/cyan]")
    console.print(f"[cyan]Question: {market_question}[/cyan]")
    console.print(f"[cyan]Outcome: {outcome}[/cyan]")
    executor = Executor()
    response = executor.get_superforecast(
        event_title=event_title, market_question=market_question, outcome=outcome
    )
    console.print("[green]Superforecaster Response:[/green]")
    console.print(response)


@app.command()
def create_market() -> None:
    """
    Format a request to create a market on Polymarket
    """
    console.print("[cyan]Generating market idea...[/cyan]")
    c = Creator()
    market_description = c.one_best_market()
    console.print("[green]Market Description:[/green]")
    console.print(market_description)


@app.command()
def ask_llm(user_input: str) -> None:
    """
    Ask a question to the LLM and get a response.
    """
    console.print(f"[cyan]Querying LLM: {user_input}[/cyan]")
    executor = Executor()
    response = executor.get_llm_response(user_input)
    console.print("[green]LLM Response:[/green]")
    console.print(response)


@app.command()
def ask_polymarket_llm(user_input: str) -> None:
    """
    What types of markets do you want to trade?
    """
    console.print(f"[cyan]Querying Polymarket LLM: {user_input}[/cyan]")
    executor = Executor()
    response = executor.get_polymarket_llm(user_input=user_input)
    console.print("[green]LLM + current markets&events response:[/green]")
    console.print(response)


@app.command()
def run_autonomous_trader() -> None:
    """
    Let an autonomous system trade for you.
    """
    console.print("[yellow]⚠️  Starting autonomous trader...[/yellow]")
    console.print("[yellow]⚠️  Please review Terms of Service: https://polymarket.com/tos[/yellow]")
    
    trading_strategy = getenv("trading_strategy")
    trader = Trader(trading_strategy)
    console.print(f"[yellow]Using trading strategy: {trading_strategy}...[/yellow]")
    dry_run = bool(literal_eval(getenv("dry_run"))) 
    if trader.trading_strategy == "ai_one_best_trade":
        trader.ai_one_best_trade()
    elif trader.trading_strategy == "arbitrage":
        slug = getenv("arbitrage_series_slug")
        dry_run_initial_trade = bool(literal_eval(getenv("dry_run_initial_trade"))) 
        trader.arbitrage(dry_run_initial_trade, slug)
        while True:
            trader.arbitrage(dry_run, slug)
    else:
        console.print(f"[red]Trading strategy {trading_strategy} is unknown, exiting without trading[/red]")    
    console.print("[green]Autonomous trading completed![/green]")


if __name__ == "__main__":
    app()
