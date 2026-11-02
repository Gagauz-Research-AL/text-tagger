#_ docker build -t text-tagger . && docker run -d -p 8000:8000 text-tagger
docker container rm text-tagger-container 
docker build -t text-tagger . && docker run -p 8000:8000 --name text-tagger-container text-tagger