# Hokie Rec

Hokie Rec is a web application for managing intramural sports leagues. Players can find leagues, form teams, manage rosters, and follow their games. Officials can manage assignments and report results, while administrators can organize leagues, schedules, and users.

The project was created for a database course and uses fictional data for its local demonstration.

## Features

- **Accounts:** Sign up, sign in, sign out, edit a profile, and change a password. Administrators can create player, official, and administrator accounts.
- **Leagues and teams:** Browse leagues and registration status, register a team, invite players, manage a roster, and follow team membership and games.
- **Scheduling:** View games and scores. Administrators can create individual games, generate regular-season schedules, manage games, and assign officials.
- **Officials and results:** Accept or decline assignments, submit game results or forfeits, and view result history. Corrections preserve earlier reports.
- **Playoffs and incidents:** Generate and manage eligible playoff brackets, advance winners, file incident reports, and review incidents.
- **Reports:** View league standings and participation summaries based on current application data.

## Screenshots

<!-- Add screenshots to docs/screenshots/ and replace these placeholders with Markdown image links. -->

### Home and leagues

*Screenshot placeholder: home page or league directory.*

### Team and schedule

*Screenshot placeholder: team page or game schedule.*

### Administration and reports

*Screenshot placeholder: an administrator workflow and/or the reports page.*

## Technology

| Layer | Technologies |
| --- | --- |
| Frontend | React, TypeScript, Vite |
| Backend | Python, FastAPI, psycopg |
| Database | PostgreSQL 17, Docker Compose |
| Authentication | Server-side sessions and Argon2 password hashing through `pwdlib` |

The browser sends requests to the FastAPI backend. The backend validates requests, applies permissions and application rules, and queries PostgreSQL. Responses are returned to the frontend for display. Database constraints, views, and triggers also enforce and support project rules.

## Local setup

### Prerequisites

- Python and `pip`
- Node.js and npm
- Docker with Docker Compose

The following commands use PowerShell and start in the project root. On macOS or Linux, use the equivalent commands for copying `.env.example` and activating the virtual environment.

### 1. Configure the environment

```powershell
Copy-Item .env.example .env
```

The example configuration is for local development. The database password in `DATABASE_URL` must match `POSTGRES_PASSWORD`. The default frontend origin is `http://localhost:5173`.

### 2. Create the database and add sample data

Start Docker, then run:

```powershell
docker compose up -d
npm run seed
```

On a new Docker volume, PostgreSQL initializes the schema from the scripts in `db/`. Run the seed command **once on a fresh database**; it adds fictional sample data and is not intended to be rerun on the same data.

### 3. Set up and start the backend

In a terminal at the project root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python migrate.py
python -m seeds.seed_demo_accounts --development
uvicorn main:app --reload
```

The backend runs at `http://localhost:8000`; interactive API documentation is available at `http://localhost:8000/docs`. The migration command updates an existing compatible database and can be rerun. On a newly initialized database, it ensures the same migrations are in place.

### 4. Set up and start the frontend

In a second terminal at the project root:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Keep both the frontend and backend terminals running while using the application.

## Demo accounts and data

The account-seeding command creates credentials for the fictional users in the sample data. The default demo password is **`hokie`**. These shared credentials are intended only for local development and demonstrations.

| Role | Example PID | Starting point |
| --- | --- | --- |
| Player | `simvt0001` | Teams and personal games |
| Official | `simvt0121` | Assignments and score entry |
| Administrator | `simvt0133` | Administration and schedule management |

Account seeding preserves existing credentials by default, so an account whose password has already been changed may not use the default. To choose a different shared demo password when provisioning accounts, use `python -m seeds.seed_demo_accounts --development --custom-password`. Adding `--reset` replaces seeded users' passwords and revokes their sessions; it does not reset accounts created through signup.

Sample league registration windows and games have specific dates, so availability changes over time. To set up a game for trying score entry and an upcoming game for the demo player and official, run this from `backend/` with the virtual environment active:

```powershell
python -m seeds.seed_score_demo --development --upcoming
```

The command preserves existing games and results and prints the demo game information. The upcoming game must fit within the demo league's season and an available time slot.

## Tests and checks

Start the database first. From `backend/`, with the virtual environment active:

```powershell
python -m unittest discover -v
```

The integration tests use temporary PostgreSQL schemas in the configured database and remove those schemas afterward.

From `frontend/`:

```powershell
npm run build
npm run lint
```

## Security

Passwords entered in the application are hidden in the interface and stored as salted hashes, not plaintext. The backend uses parameterized queries for user-supplied values to help prevent SQL injection, and checks roles and permissions for protected actions. The shared seeded password and example environment settings are for local development only.

## Repository guide

| Path | Contents |
| --- | --- |
| `frontend/` | React interface |
| `backend/` | API, application logic, migrations, and tests |
| `db/` | Database schema, rules, and sample-data scripts |
| `docs/` | ER diagram and project materials |
| `compose.yaml` | Local PostgreSQL container configuration |

The current ER diagram is in [docs/er-diagram.md](docs/er-diagram.md).
