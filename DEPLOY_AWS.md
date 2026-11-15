# Déployer Peace sur AWS (EC2, Ubuntu 24.04)

1. **Créer l'instance** : console AWS > EC2 > Launch instance. Image *Ubuntu Server 24.04 LTS*, type `t3.small` (ou `t3.micro`).
   Groupe de sécurité : autoriser **SSH (22)** et un **TCP personnalisé 8080** depuis `0.0.0.0/0`.
2. **Rôle pour Bedrock** : joindre à l'instance un rôle IAM avec la permission `bedrock:InvokeModel`
   (EC2 > Actions > Security > Modify IAM role). Les identifiants sont alors fournis par AWS, jamais écrits dans un fichier.
3. **Se connecter** (EC2 Instance Connect dans la console) puis :

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv git
git clone https://github.com/apalumbo848-prog/peace-agent.git
cd peace-agent
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

4. **Lancer** (reste actif après la déconnexion) :

```bash
export AWS_DEFAULT_REGION=us-east-1 PEACE_HOST=0.0.0.0 PEACE_ALLOWED_HOSTS='*' PORT=8080
nohup python -m agent_risque.app.server > peace.log 2>&1 &
```

5. **Adresse publique** : `http://<IP publique de l'instance>:8080/` (EC2 > Instances > Public IPv4 address).

Mise à jour : `git pull` puis relancer (`pkill -f agent_risque.app.server`, puis la commande de l'étape 4).
