# CSV Username Builder + Moodle Uploader

A web application that helps you:

- Upload a CSV file with **First Name, Last Name, Email Address** (and optional Course IDs).
- Automatically generate **usernames** (handling duplicates, accents, formatting).
- Preview and download a cleaned CSV with Moodle-ready usernames.
- Sync directly with **Moodle** via Web Services API:
  - Create users if they don’t exist.
  - Unsuspend existing accounts.
  - Enrol users into provided courses.

Frontend built with vanilla HTML/JS (CSV preview, progress, logging).  
Backend built with **Flask** + **Requests**.

---

## 🚀 Features

- Drag-and-drop CSV upload + live preview.
- Auto-generate unique usernames.
- Export processed CSV with preserved columns.
- Moodle API integration:
  - Create users with strong passwords.
  - Check if user exists by email.
  - Unsuspend suspended accounts.
  - Enrol in courses with role ID (default: Student).
- Live logs + progress bar using **Server-Sent Events (SSE)**.

---

## 📂 Project Structure

```

.
├── app.py              # Flask backend (API routes + Moodle sync)
├── requirements.txt    # Python dependencies
├── .env                # Local environment variables (NOT for production!)
├── templates/
│   └── index.html      # Web UI (CSV upload, preview, logs, etc.)

````

---

## ⚙️ Requirements

- Python 3.10+ recommended
- Moodle with a configured **Web Service token** that has permission to:
  - `core_user_create_users`
  - `core_user_get_users_by_field`
  - `enrol_manual_enrol_users`
  - `core_user_update_users`

---

## 🔧 Local Development

1. **Clone the repo**

   ```bash
   git clone https://github.com/yourusername/moodle-uploader.git
   cd moodle-uploader
````

2. **Set up virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate   # on macOS/Linux
   venv\Scripts\activate      # on Windows
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**

   Copy `.env.example` to `.env` and set values:

   ```ini
   MOODLE_URL=https://yourmoodle/webservice/rest/server.php
   MOODLE_TOKEN=yourmoodleapitoken
   MOODLE_ROLE_ID=5   # optional, defaults to Student
   ```

5. **Run the app**

   ```bash
   python app.py
   ```

6. Open in browser → [http://localhost:5000](http://localhost:5000)

---

## 🌍 Deployment (Render free tier)

1. Push code to **GitHub**.
2. Go to [Render Dashboard](https://dashboard.render.com).
3. **New → Web Service**.
4. Connect your GitHub repo and select branch.
5. Configure:

   * **Build Command**:

     ```
     pip install -r requirements.txt
     ```
   * **Start Command**:

     ```
     gunicorn app:app
     ```
6. Add environment variables (`MOODLE_URL`, `MOODLE_TOKEN`, etc.) in **Environment** section.
7. Deploy → you’ll get a live URL like `https://yourapp.onrender.com`.

---

## 🛡️ Security Notes

* **Do not commit `.env`** to GitHub. Add it to `.gitignore`.
* Store secrets (Moodle tokens) in your hosting provider’s environment variables.
* Use HTTPS for all connections to your app.

---

## 📜 License

MIT License — feel free to use, modify, and share.

---

## 🙌 Credits

* Frontend CSV parsing with [PapaParse](https://www.papaparse.com/).
* Backend: Flask + Requests.
* Moodle integration via [Moodle Web Services API](https://docs.moodle.org/dev/Web_service_API_functions).

```

---

Do you want me to also generate a **`.env.example` file** for your repo, so people know what keys to set but without exposing real secrets?
```
