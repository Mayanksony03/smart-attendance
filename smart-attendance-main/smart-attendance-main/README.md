Smart Attendance System 🎓
Face-recognition based attendance system — Flask + MongoDB Atlas + OpenCV.
---
Step 1 — Create a Free MongoDB Atlas Database
Go to https://mongodb.com/atlas and sign up free
Create a free M0 cluster (choose any region)
Click Database Access → Add new user → set username + password
Click Network Access → Add IP Address → Allow access from anywhere (0.0.0.0/0)
Click Connect on your cluster → Drivers → Copy the connection string
It looks like this:
```
   mongodb+srv://YOUR_USER:YOUR_PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
---
Step 2 — Deploy to Railway
Push code to GitHub:
```bash
   git init
   git add .
   git commit -m "initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```
Go to https://railway.app → New Project → Deploy from GitHub repo
Select your repo
Go to Variables tab → click New Variable → add:
Name:  `MONGO_URI`
Value: `mongodb+srv://YOUR_USER:YOUR_PASSWORD@cluster0.xxxxx.mongodb.net/attendance_system?retryWrites=true&w=majority`
Railway restarts and your app is live ✅
---
Step 3 — Deploy to Render (Alternative)
Go to https://render.com → New → Web Service
Connect your GitHub repo
Set Build Command: `pip install -r requirements.txt`
Set Start Command: `python app.py`
Go to Environment tab → Add variable:
Key:   `MONGO_URI`
Value: `mongodb+srv://YOUR_USER:YOUR_PASSWORD@cluster0.xxxxx.mongodb.net/attendance_system?retryWrites=true&w=majority`
Click Deploy ✅
---
Local Development
Set the environment variable before running:
```bash
# Windows
set MONGO_URI=mongodb+srv://...

# Mac / Linux
export MONGO_URI=mongodb+srv://...

python app.py
```
---
Project Structure
```
├── app.py                  # Flask routes
├── face_utils.py           # Face recognition logic (MongoDB)
├── db.py                   # MongoDB connection
├── requirements.txt        # Python dependencies
├── Procfile                # Start command for Railway/Render
├── .gitignore
├── templates/
│   ├── index.html
│   ├── register.html
│   ├── attendance.html
│   ├── sessions.html
│   ├── report.html
│   ├── create_session.html
│   └── delete.html
└── static/
    └── style.css
```
---
Important Notes
No `database.db` needed — MongoDB Atlas stores everything in the cloud permanently
Data survives all redeployments on Railway and Render
MONGO_URI is secret — never push it to GitHub, always use environment variables
Webcam works from browser — JavaScript captures photo, sends to Flask as base64
