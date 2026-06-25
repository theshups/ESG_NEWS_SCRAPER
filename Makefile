frontend:
	venv\\Scripts\\uvicorn.exe api.app:app --reload --port 8000

scrape:
	venv\\Scripts\\python.exe main.py --mode keyword

scrape-hf:
	venv\\Scripts\\python.exe main.py --mode hf

evaluate:
	venv\\Scripts\\python.exe evaluate.py

scheduler:
	venv\\Scripts\\python.exe scheduler.py

export-logs:
	venv\\Scripts\\python.exe main.py --export-logs

build:
	docker-compose build

run:
	docker-compose up -d

stop:
	docker-compose down

restart:
	docker-compose down
	docker-compose up -d

logs:
	docker-compose logs -f app

status:
	docker-compose ps

health:
	curl -s http://localhost:8000/health

clean:
	docker-compose down -v

clean-old:
	venv\\Scripts\\python.exe clean_old.py
