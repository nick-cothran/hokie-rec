# Hokie Rec Demo Workflow

This walkthrough follows a player joining a league, an official handling a game, and an administrator managing the system. Allow approximately 10–15 minutes, depending on how many optional actions you demonstrate.

## Before the demo

Start the database, backend, and frontend using the setup instructions in the project README. Open `http://localhost:5173`.

From the `backend` folder, with the virtual environment active, prepare a fresh game for score entry and an upcoming assignment:

```powershell
python seed_score_demo.py --development --new-game --upcoming
```

The command prints the score-entry game's address. Keep that terminal visible so you can find it if needed. It adds a new unscored game and preserves existing results.

Use these fictional accounts:

| Role | PID | Default demo password |
| --- | --- | --- |
| Player | `simvt0001` | `hokie` |
| Second player | `simvt0002` | `hokie` |
| Official | `simvt0121` | `hokie` |
| Administrator | `simvt0133` | `hokie` |

These passwords work if they have not been changed since the demo accounts were seeded. Before presenting, check that a league is open for registration and that the upcoming game appears. League windows and game dates change with time.

## 1. Introduce the site and browse leagues

Start signed out.

1. Show the home page and explain that Hokie Rec supports players, officials, and administrators.
2. Open **Leagues**.
3. Point out the filters and registration status for each league.
4. Open a league to show its teams, schedule link, standings link, and playoff bracket if one exists.

**What to say:** “A student can explore leagues and see whether registration is open before signing in.”

## 2. Show signup and the player experience

1. Open **Sign in**, then choose the signup option.
2. Show the signup form and explain that new users create player accounts. Create an account with a unique PID and email, or leave the form unsubmitted to save time.
3. Sign in as `simvt0001`.
4. Open **Account** and show profile editing and the password-change options. The password-change form first asks for the current password.
5. Open **Teams** and point out **Your teams**.
6. Open **Schedule** and show **Your games**, including the upcoming demo game.

**What to say:** “Once signed in, a player can manage their profile and quickly see their own teams and games.”

## 3. Register a team and manage its roster

1. While signed in as `simvt0001`, go to **Teams → Register a team**.
2. Choose an open league in which this player is **not already on a team**. Enter a unique team name and register.
3. Show that the player becomes the team captain.
4. On the team page, show the roster and rename the team.
5. Invite another player by PID. Choose a player who is not already active on a team in that league.
6. Sign out, sign in as the invited player, and accept the invitation.
7. Return to the team page and show the updated roster.

To demonstrate **delete** for the CRUD requirement, delete this demonstration team after the roster example and **before scheduling any games for it**. A team with games cannot be deleted.

**What to say:** “Captains can create and manage teams, while invited players must accept before joining the roster.”

## 4. Show the official workflow

1. Sign out and sign in as `simvt0121`.
2. On **Schedule**, point out the assignments needing action.
3. Find the upcoming demo game and **accept** its assignment.
4. Find the ended, unscored demo game created during preparation and select **Enter result**. If it is difficult to locate, use the game address printed by the preparation command.
5. Enter a score, such as **3–1**, and submit it.
6. Show the result history. Submit a correction, such as **3–2**, and point out that the earlier report remains visible.
7. Open **Incidents**, select an assigned game, and submit a short fictional incident report.

**What to say:** “Officials see their assigned games, enter results after games end, and can correct a result without erasing the original submission.”

## 5. Show administrator features

1. Sign out and sign in as `simvt0133`.
2. On **Admin**, show the user list and the form for creating a player, official, or administrator. Create a fictional user with a unique PID and email, or show the form without submitting it.
3. Open **Manage sports, leagues & facilities**. Show how an administrator can add or edit these records. For another CRUD example, create a temporary facility, edit its name, and delete it while it is unused.
4. Open **Schedule** and select a league. Show **Schedule a game** and the expandable options for generating schedules, assigning officials, and managing games.
5. Open **Incidents** and mark the fictional report from the official workflow as reviewed.

**What to say:** “Administrators manage the information needed to run leagues and can review incidents filed by officials.”

For a live game-creation example, choose two active teams in the same league, a free facility, and a future time within the league's season. Identify those choices before presenting.

## 6. Finish with reports

1. Open **Reports**.
2. Select the demo league in **League standings** and show the game result you entered.
3. Scroll to **League participation** and explain the counts for teams, active players, invitations, and games.
4. Return to the league page and show its bracket, if available.

**What to say:** “These reports summarize information from the database. Standings use game results, while participation combines league, team, roster, and schedule data.”

For a shorter presentation, prioritize **league browsing → team registration → official score entry → admin tools → reports**. Practice the full sequence once beforehand, particularly the invitation and scheduling steps, since those depend on the current database state.
