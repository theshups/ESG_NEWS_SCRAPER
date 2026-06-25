from dotenv import load_dotenv
load_dotenv()
from src.components.database import PostgreSQLStorage

db = PostgreSQLStorage()
n  = db.delete_old_articles(days=7)
print(str(n) + " articles deleted from database")