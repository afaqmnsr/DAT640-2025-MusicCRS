# Group project: DAT640-1 25H Informasjonsgjenfinning og tekstutvinning

## Group project

### Group formation
- **Group size:** Each group must have **2 members**. If you cannot form a group on your own, the lecturer will assign you to a group. Lecturer-assigned groups may have **up to 3 members**.
- **Registration:** Everyone must fill out this form **by Sep 24 (23:59):**  
  https://forms.gle/iLwsKpYJrgjqt73v5
- **Equal contribution:** All group members must contribute equally. If unequal contributions are suspected, points may be deducted from the member not contributing sufficiently.
- **Group changes:** Group changes are **not allowed**. For extraordinary circumstances (e.g. a member becomes unavailable), contact the lecturer immediately.

## Project requirements

**Task:** Develop a **conversational music recommender system** based on the specified requirements.

**Requirements:** All requirements are released at once.

- Each set of requirements includes a list of subtasks/features.
- You may choose which of these to complete.
- Some requirements build on previous features and can **only** be completed once the prerequisites are fulfilled.
- The maximum points for each feature will be specified.
- Full or partial points may be awarded based on how well the feature works.
- In some requirement sets there may be features for **more than 10 points overall**, giving you options to choose from.  
  👉 The **total number of points** earned for each requirement set **cannot exceed 10**.

**Data, tools and languages:**
- Programming language: **Python**
- You are required to build on top of:
  - **DialogueKit** (dialogue management): https://github.com/iai-group/dialoguekit
  - **ChatWidget** (web-based UI): https://github.com/iai-group/ChatWidget
- A **large language model**, hosted at UiS, can be used through a shared API.
- A **starting package** based on these tools is made available:  
  https://github.com/iai-group/dat640-2025-MusicCRS
- All teams are required to use the **Spotify Million Playlist Dataset**:  
  Challenge page: https://www.aicrowd.com/challenges/spotify-million-playlist-dataset-challenge  
  Direct download: https://gustav1.ux.uis.no/downloads/spotify_million_playlist_dataset/mpd.v1.tar

## Grading criteria

- **Point allocation:** Points can be earned for each set of requirements, totaling a **maximum of 70 points** for the entire project.
- **Deadlines:** Points may only be awarded for a set of requirements if it's submitted/presented **by the deadline**.
- Because later features depend heavily on **R2** and **R3**, there is an **additional requirement** of demonstrating these by **Oct 19**.  
  - Groups **failing** to do so or **scoring 0 points** on either **R2 or R3** will **not** be allowed to earn points for **R4–R7**.
- **Assessment basis:** Most of the requirements will need to be **demonstrated in person** to the lecturers; **R1 and R6** are to be submitted online.

**Important:**
- You are allowed **only one attempt** to present and earn points for **each set of requirements (Rx)**.
  - You **cannot** present some subtasks of Rx in one session and others from the same Rx in another session.
  - You may choose not to implement a feature by the deadline, but if a future feature depends on it, you will have to implement it later **without** earning points for it.

**In-person demonstrations:**
- Demonstrations can be scheduled during lecture slots on **Tuesdays and Fridays**.
- Use the booking system to schedule your demo:  
  https://calendly.com/galuscakova/15min
  - Write your **group number** and the **list of requirements** you plan to present in the comment.
  - To cancel, contact Petra directly. **No-show = 0 points** for the requirements you planned to present.
  - Since slots are fewer than groups, **book early**.
- All group members must be present and prepared to discuss their contributions.
- Aim to present **at least two** sets of requirements per in-person demo for efficient use of time.

## General requirements
- Responses need to be generated within **3–5 seconds**.
- There is **a single LLM call allowed per turn**.

## R1: Collecting music preferences

- **Deadline:** **w40 (Oct 03)**
- **Delivery:** online submission using this form:  
  https://forms.gle/DNeARqPjj7oUsaKp6

**Task:** Specify music preferences of real users and create playlists for specific (self-defined) contexts.

| Subtask | Description | Points | Dependencies |
|--------|-------------|--------|--------------|
| **R1.1** | Two playlists/profiles (one per group member) | **4p** | — |
| **R1.2** | Up to three additional playlists/profiles by other people (friends, family, etc.) | **6p** | — |

(Max 10p for R1.)

## R2: Web-based UI

- **Deadline:** **w42 (Oct 21)**
- **Delivery:** **in-person demo**

**Task:** Set up and configure a web-based chat environment where the user can interact with the music recommender system.

**Requirements:**
- User can **add/remove songs**, **view** playlist, **clear** playlist via **natural language** or **commands**.
- Only tracks that exist in the **Spotify Million Playlist Dataset** may be added.
- At this point, the system can require exact formats; no need to deal with noisy inputs.

| Subtask | Description | Points | Dependencies |
|--------|-------------|--------|--------------|
| **R2.1** | Set up a web-based chat environment. | **1p** | — |
| **R2.2** | Add/remove/view/clear playlist; integrate Spotify MPD as database; add songs by artist+title. | **4p** | — |
| **R2.3** | Extend UI so user can interact directly with the playlist (not just via chat). | **3p** | R2.1 |
| **R2.4** | Provide a way for the user to learn about the functionality of the system. | **1p** | — |
| **R2.5** | Support multiple playlists. | **2p** | R2.2 |
| **R2.6** | Display image cover for playlist (downloaded or generated) based on playlist characteristics. | **2p** | R2.1 |

## R3: Music database and basic QA functionality

- **Deadline:** **w42 (Oct 21)**
- **Delivery:** **in-person demo**

**Task:** Create and populate a **music database** containing all tracks from the dataset. Allow the user to ask basic questions about tracks and artists. Answers must come from the **database**, not the LLM.

| Subtask | Description | Points | Dependencies |
|--------|-------------|--------|--------------|
| **R3.1** | Add songs by just a **title**; if ambiguous, offer user-friendly disambiguation. | **2p** | R2.2 |
| **R3.2** | Rank disambiguation suggestions intelligently (popularity/similarity). | **1p** | R3.1 |
| **R3.3** | Let user ask questions about tracks and artists (support 4 types of questions). | **4p** | R2.2 |
| **R3.4** | Questions about compilation albums (e.g. “Which artist appears most in ‘Best of 90s’?”). | **1p** | R2.2 |
| **R3.5** | Textual or visual summary of playlist with basic statistics. | **2p** | R2.2 |
| **R3.6** | Add possibility to play song or preview (e.g. Spotify Playback SDK). | **2p** | R2.2 |

## R4: Recommendations

- **Deadline:** **w44 (Nov 4)**
- **Delivery:** **in-person demo**

**Task:**  
(a) Recommend additional songs for an existing playlist, **and/or**  
(b) Create a playlist from scratch based on a **natural language description**.

| Subtask | Description | Points | Dependencies |
|--------|-------------|--------|--------------|
| **R4.1** | New `recommend` command suggests 3–5 related songs (not random); use existing human playlists. | **4p** | R2.2 |
| **R4.2** | Let user select which recommended songs to add (e.g. checklist or indices). | **1p** | R4.1 |
| **R4.3** | Explain **why** each track was recommended. | **2p** | R4.1 |
| **R4.4** | New command to create a whole playlist from a natural language description. | **3p** | R2.2 |
| **R4.5** | Determine playlist length **intelligently** (no explicit user ask). | **1p** | R4.4 |
| **R4.6** | Auto-generate a playlist name from chosen songs. | **2p** | R4.4 |

## R5: Natural language interactions

- **Deadline:** **w44 (Nov 4)**
- **Delivery:** **in-person demo**

**Goal:** Let users express intents in **free text**, not only fixed commands. Handle fuzzy song/artist names and ambiguities.

| Subtask | Description | Points | Dependencies |
|--------|-------------|--------|--------------|
| **R5.1** | Allow playlist manipulation via natural language (add/remove/view/clear); extract parameters via fine-tuned model or LLM. | **4p** | R2.2 |
| **R5.2** | Allow natural language selection of recommended songs (e.g. “add the first two”, “add all”, “add all except…”). **1p each**, max **3p**. | **3p** | R4.2 |
| **R5.3** | Add support for “just a song name” (R3.1) **in natural language**. | **1p** | R5.1, R3.1 |
| **R5.4** | Ask the R3.3 questions **in natural language**. | **1p** | R5.1, R3.3 |
| **R5.5** | Natural language for the recommend command (R4.1). | **1p** | R5.1, R4.1 |
| **R5.6** | Allow simplified entry of complex song names (e.g. special chars, parentheses). | **2p** | R5.3 |

## R6: Interactions with a user simulator via an API

- **Deadline:** **w45 (Nov 11)**
- **Delivery:** **online submission**

A simulator API will be provided. It will try to create a playlist using your system. Points are based on:
- successful interactions,
- ability to create a playlist,
- quality of recommendations (using R1 data as ground truth).

Minimalistic simulator for testing:  
https://github.com/iai-group/dat640-2025-MusicCRS/tree/main/simulation

| Subtask | Description | Points | Dependencies |
|--------|-------------|--------|--------------|
| **R6.1** | Connect to simulator and conduct interactions for **2+ turns**. | **2p** | — |
| **R6.2** | Successfully create a playlist using **command-based** interactions. | **2p** | R2.2, R6.1 |
| **R6.3** | Successfully create a playlist using **natural language**, including disambiguation. | **4p** | R5.1, R5.3, R6.1 |
| **R6.4** | Provide recommendations that match user preferences. | **2p** | R4.1, R6.1 |
| **R6.5** | Generate entire playlists based on natural language descriptions. | **2p** | R4.4, R6.1 |

## R7: Advanced functionality

- **Deadline:** **w46 (Nov 14)**
- **Delivery:** **in-person demo**
- Idea must be submitted in Canvas by **w44 (Oct 31)**:  
  https://stavanger.instructure.com/courses/16518/assignments/43508

**Task:** Propose and implement **a new feature** that improves usability or performance of the system for real users, leveraging course techniques. Points depend on **difficulty** and **execution**.

## Useful links (collected)

- Group registration form: https://forms.gle/iLwsKpYJrgjqt73v5
- R1 submission form: https://forms.gle/DNeARqPjj7oUsaKp6
- Demo booking: https://calendly.com/galuscakova/15min
- DialogueKit: https://github.com/iai-group/dialoguekit
- ChatWidget: https://github.com/iai-group/ChatWidget
- Starter package (MusicCRS): https://github.com/iai-group/dat640-2025-MusicCRS
- Spotify MPD challenge: https://www.aicrowd.com/challenges/spotify-million-playlist-dataset-challenge
- Spotify MPD download: https://gustav1.ux.uis.no/downloads/spotify_million_playlist_dataset/mpd.v1.tar
- Simulator folder: https://github.com/iai-group/dat640-2025-MusicCRS/tree/main/simulation
- Canvas (R7 idea): https://stavanger.instructure.com/courses/16518/assignments/43508
