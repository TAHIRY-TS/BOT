# Utilise une image Python légère
FROM python:3.11-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers
COPY . .

# Installer les dépendances
RUN pip install --no-cache-dir -r requirements.txt

# Exposer le port utilisé par Flask (8080)
EXPOSE 8080

# Lancer l’application
CMD ["python", "main.py"]
