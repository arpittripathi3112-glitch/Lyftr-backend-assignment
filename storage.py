import logging
from datetime import datetime, timezone
from typing import Generator, Optional, Tuple

from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from sqlalchemy.exc import IntegrityError

from app.config import settings

logger = logging.getLogger(__name__)

# Create SQLAlchemy engine with SQLite-specific settings
# check_same_thread=False is required for SQLite to work with FastAPI's async
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

# Create SessionLocal class for creating database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for SQLAlchemy models
Base = declarative_base()


def init_db() -> None:
    """
    Initialize the database by creating all tables.
    Called during application startup.
    """
    logger.debug(f"Initializing database with URL: {settings.DATABASE_URL}")
    try:
        # Import models to register them with Base.metadata
        from app.models import Message  
        
        logger.debug("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


def get_db() -> Generator[Session, None, None]:
    """
    Dependency to get database session.
    Yields a session and ensures it's closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_health() -> bool:
    """
    Check if the database is reachable and schema is applied.
    
    Returns:
        True if DB is healthy and schema exists, False otherwise.
    """
    logger.debug("Checking database health...")
    try:
        with SessionLocal() as db:
            # Execute a simple query to check connectivity
            logger.debug("Testing database connectivity...")
            db.execute(text("SELECT 1"))
            logger.debug("Database connectivity OK")
            
            # Check if messages table exists (schema is applied)
            logger.debug("Checking for messages table...")
            db.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
            ))
            result = db.execute(text(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='messages'"
            )).scalar()
            if result == 0:
                logger.error("Database schema not applied: 'messages' table not found")
                return False
            logger.debug("Messages table found, schema is applied")
        logger.debug("Database health check passed")
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


# =============================================================================
# Message Repository Functions
# =============================================================================

def create_message(
    db: Session,
    message_id: str,
    from_msisdn: str,
    to_msisdn: str,
    ts: str,
    text: Optional[str] = None
) -> Tuple[bool, bool]:
    """
    Create a new message in the database (idempotent).

    Args:
        db: Database session
        message_id: Unique message identifier
        from_msisdn: Sender phone number
        to_msisdn: Recipient phone number
        ts: Message timestamp (ISO-8601 UTC)
        text: Optional message text

    Returns:
        Tuple of (success: bool, is_duplicate: bool)
        - (True, False): Message created successfully
        - (True, True): Message already exists (duplicate, idempotent success)
        - (False, False): Error occurred
    """
    from app.models import Message

    logger.info(f"Creating message: id={message_id}, from={from_msisdn}, to={to_msisdn}")
    logger.debug(f"Message details: ts={ts}, text={text}")

    try:
        # Create server timestamp
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.debug(f"Server timestamp: {created_at}")

        message = Message(
            message_id=message_id,
            from_msisdn=from_msisdn,
            to_msisdn=to_msisdn,
            ts=ts,
            text=text,
            created_at=created_at
        )

        db.add(message)
        db.commit()
        logger.info(f"Message created successfully: {message_id}")
        return (True, False)  # Created successfully, not a duplicate

    except IntegrityError:
        # message_id already exists - this is expected for idempotency
        db.rollback()
        logger.info(f"Duplicate message detected: {message_id}")
        return (True, True)  # Success (idempotent), is duplicate

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create message {message_id}: {e}")
        return (False, False)  # Error


def get_message_by_id(db: Session, message_id: str):
    """
    Retrieve a message by its ID.

    Args:
        db: Database session
        message_id: Message identifier to look up

    Returns:
        Message object if found, None otherwise
    """
    from app.models import Message

    logger.info(f"Looking up message by ID: {message_id}")
    result = db.query(Message).filter(Message.message_id == message_id).first()
    logger.info(f"Message lookup result: {'found' if result else 'not found'}")
    return result


def get_messages(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    from_msisdn: Optional[str] = None,
    since: Optional[str] = None,
    q: Optional[str] = None
) -> Tuple[list, int]:
    """
    Retrieve messages with pagination and filtering.

    Args:
        db: Database session
        limit: Maximum number of messages to return (1-100)
        offset: Number of messages to skip
        from_msisdn: Filter by sender (exact match)
        since: Filter messages with ts >= since (ISO-8601 UTC)
        q: Free-text search in message text (case-insensitive)

    Returns:
        Tuple of (messages list, total count matching filters)
    """
    from app.models import Message

    logger.info(f"Querying messages: limit={limit}, offset={offset}")
    logger.debug(f"Filters: from={from_msisdn}, since={since}, q={q}")

    # Build base query
    query = db.query(Message)

    # Apply filters
    if from_msisdn:
        query = query.filter(Message.from_msisdn == from_msisdn)
        logger.debug(f"Applied from filter: {from_msisdn}")

    if since:
        query = query.filter(Message.ts >= since)
        logger.debug(f"Applied since filter: {since}")

    if q:
        # Case-insensitive substring search
        query = query.filter(Message.text.ilike(f"%{q}%"))
        logger.debug(f"Applied text search filter: {q}")

    # Get total count before pagination
    total = query.count()
    logger.debug(f"Total messages matching filters: {total}")

    # Apply ordering: ts ASC, message_id ASC (deterministic)
    query = query.order_by(Message.ts.asc(), Message.message_id.asc())

    # Apply pagination
    messages = query.offset(offset).limit(limit).all()
    logger.info(f"Retrieved {len(messages)} of {total} total messages")

    return messages, total


def get_stats(db: Session) -> dict:
    """
    Get message statistics for the /stats endpoint.
    
    Computes:
    - total_messages: count of all messages
    - senders_count: number of unique senders
    - messages_per_sender: top 10 senders by message count (desc)
    - first_message_ts: earliest timestamp (null if no messages)
    - last_message_ts: latest timestamp (null if no messages)
    
    Returns:
        Dictionary with stats data
    """
    from app.models import Message
    
    logger.info("Computing message statistics")
    
    # Get total message count
    total_messages = db.query(func.count(Message.message_id)).scalar() or 0
    logger.debug(f"Total messages: {total_messages}")
    
    # Get unique senders count
    senders_count = db.query(func.count(func.distinct(Message.from_msisdn))).scalar() or 0
    logger.debug(f"Unique senders: {senders_count}")
    
    # Get top 10 senders by message count (descending)
    messages_per_sender_query = (
        db.query(
            Message.from_msisdn,
            func.count(Message.message_id).label("count")
        )
        .group_by(Message.from_msisdn)
        .order_by(func.count(Message.message_id).desc())
        .limit(10)
        .all()
    )
    messages_per_sender = [
        {"from": row.from_msisdn, "count": row.count}
        for row in messages_per_sender_query
    ]
    logger.debug(f"Top senders: {len(messages_per_sender)}")
    
    # Get first and last message timestamps
    first_message_ts = db.query(func.min(Message.ts)).scalar()
    last_message_ts = db.query(func.max(Message.ts)).scalar()
    logger.debug(f"First message: {first_message_ts}, Last message: {last_message_ts}")
    
    logger.info(f"Stats computed: {total_messages} messages, {senders_count} senders")
    
    return {
        "total_messages": total_messages,
        "senders_count": senders_count,
        "messages_per_sender": messages_per_sender,
        "first_message_ts": first_message_ts,
        "last_message_ts": last_message_ts
    }
