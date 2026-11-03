# 🎓 T&P Connect

### Connecting Students with Opportunities. Simplifying Campus Placements.

**T&P Connect** is a web-based platform designed to make college placement activities easier, faster, and more organized. It brings students and the Training & Placement Cell together through a single platform for managing placement drives, checking eligibility, tracking applications, and sharing important updates.

---

## ✨ Key Features

- 👨‍🎓 **Student Management** – Manage student records and import data using CSV.
- 🏢 **Placement Drives** – Create, publish, and manage company placement drives.
- 📄 **Circular Analyzer** – Extract information from placement circular PDFs.
- ✅ **Eligibility Checker** – Check student eligibility based on company requirements.
- 📊 **Application Tracking** – Track applications and recruitment rounds.
- 🔔 **Notifications** – Share placement updates with students.

## 📸 Project Screenshots

*Screenshots of the working application.*

### Welcome Page
<img width="1911" height="955" alt="Welcome page" src="https://github.com/user-attachments/assets/9b06009e-e0d5-4c62-9752-52103a3694de" />


### Admin and Student Dashboard
<img width="1892" height="957" alt="Admin dashboard" src="https://github.com/user-attachments/assets/618d5f22-a468-455e-b2f7-119a5bc8e24f" />
<img width="1920" height="972" alt="Student dashboard" src="https://github.com/user-attachments/assets/c260fbeb-7da9-429c-8a71-d89f5e0d8346" />


### Student Records
<img width="1892" height="958" alt="Student records" src="https://github.com/user-attachments/assets/a41779fa-5051-4af3-8157-22b6565ab426" />
<img width="1890" height="349" alt="Student records1" src="https://github.com/user-attachments/assets/a9a97b44-2aaf-4405-8394-ba31e7547f8c" />

### Placement Drives
<img width="1920" height="955" alt="Placement drives" src="https://github.com/user-attachments/assets/97ae38c8-3352-40ed-93e3-26a6d4451eaa" />
<img width="1879" height="969" alt="Placement drives1" src="https://github.com/user-attachments/assets/794b728b-3e61-4d0e-af9e-21c45ce2b28f" />


### Circular Analyzer
<img width="1920" height="646" alt="Circular Analyzer" src="https://github.com/user-attachments/assets/5e94e360-36c8-4408-842c-58ebf6d9c5bf" />

### Notifications
<img width="1898" height="957" alt="Notifications" src="https://github.com/user-attachments/assets/33df9c91-2095-4d14-bf04-294736cbad8a" />


---

## 🛠️ Technology Stack

| Technology | Purpose |
|---|---|
| Python | Backend programming |
| FastAPI | Web framework |
| SQLite | Database |
| SQLAlchemy | Database management |
| HTML, CSS & JavaScript | Frontend |
| Alembic | Database migrations |
| PyMuPDF | PDF text extraction |

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/karandesiddhi2006/T-P-Connect.git
cd T-P-Connect
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

### 3. Activate the environment (Windows PowerShell)

```powershell
.venv\Scripts\Activate.ps1
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure environment

Create a `.env` file using `.env.example` and configure the required settings.

### 6. Run database migrations and create an admin

```bash
alembic upgrade head
python -m scripts.create_admin
```

### 7. Start the application

```bash
python -m uvicorn app.main:app --reload
```

Open your browser and visit:

**http://127.0.0.1:8000**

---

## 🎯 Project Objective

To simplify placement management, reduce manual work, improve communication, and provide a more organized placement experience for students and the Training & Placement Cell.

## 🔮 Future Scope

- Automated email notifications
- Advanced placement analytics
- Improved placement insights and reporting
- Cloud deployment for wider accessibility

---

## 👩‍💻 Developed By

**Siddhi Karande**

[GitHub Profile](https://github.com/karandesiddhi2006)

---

⭐ If you find this project interesting, consider giving the repository a star!
