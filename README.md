
# Moodle CSV User Sync

A web application for **bulk user creation, updating, and course enrollment in Moodle** using CSV files.
Automatically generates unique usernames, cleans input data, and integrates directly with the **Moodle Web Services API**.

---

## 🚀 Features

* **CSV Import**: Upload CSV with `First Name`, `Last Name`, `Email` (+ optional Course IDs).
* **Username Builder**: Auto-generate Moodle-ready usernames (handles accents, duplicates, formatting).
* **CSV Export**: Download a cleaned CSV with preserved columns + generated usernames.
* **Moodle Sync** via API:

  * Create new users with strong passwords.
  * Unsuspend existing accounts.
  * Enrol users into courses by ID (default role: Student).
* **Frontend**: Vanilla HTML/JS with live CSV preview, progress bar, and logs.
* **Backend**: Flask + Requests with SSE (real-time logs).

---

## 📂 Project Structure

```
.
├── app.py              # Flask backend (API routes + Moodle sync)
├── requirements.txt    # Python dependencies
├── .env                # Local environment variables (DO NOT commit)
├── templates/
│   └── index.html      # Web UI (CSV upload, preview, logs)
```

---

## ⚙️ Requirements

* Python **3.10+**
* Moodle instance with a configured Web Service token granting access to:

  * `core_user_create_users`
  * `core_user_get_users_by_field`
  * `core_user_update_users`
  * `enrol_manual_enrol_users`

---

## 🛠️ Local Development

1. **Clone the repo**

   ```bash
   git clone https://github.com/yourusername/moodle-csv-user-sync.git
   cd moodle-csv-user-sync
   ```

2. **Set up virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate   # macOS/Linux
   venv\Scripts\activate      # Windows
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**

   Copy `.env.example` → `.env` and set values:

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

## 🛡️ Security Notes

* ❌ Do **not** commit `.env` (already in `.gitignore`).
* 🔑 Store secrets in hosting provider’s environment variables.
* 🔒 Always use **HTTPS** when connecting to Moodle.

---

## 🙌 Credits

* CSV parsing: [PapaParse](https://www.papaparse.com/)
* Backend: Flask + Requests
* Moodle integration: [Moodle Web Services API](https://docs.moodle.org/dev/Web_service_API_functions)

---

## 📜 License

MIT License — free to use, modify, and share.

---
