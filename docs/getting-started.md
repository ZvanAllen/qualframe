# Getting started

This guide takes you from download to your first reviewed results. Allow about 20 minutes, most of it reading the demo.

## 1. Install and start

1. Download QualFrame from GitHub and unzip it somewhere convenient, such as your Documents folder. You can also clone the repository.
2. Start it:
   - **Windows:** double-click `Start QualFrame.bat`.
   - **macOS:** double-click `start-qualframe.command`. The first time, macOS may say it can't verify the developer; right-click the file, choose **Open**, then confirm.
   - **Linux:** run `./start-qualframe.command`.

The first start downloads [uv](https://docs.astral.sh/uv/), Python 3.12 and QualFrame's packages, which takes a few minutes. After that, starting takes a few seconds. QualFrame then opens in your browser at `http://127.0.0.1:8765`. That address only works on your own computer.

Keep the start window open while you use QualFrame. Closing it stops the app; your work is saved as you go.

**Where studies are saved:** in a `QualFrame` folder in your home directory (`%USERPROFILE%\QualFrame` on Windows, `~/QualFrame` on a Mac). This keeps your data separate from the application, so you can update or reinstall QualFrame without touching your studies. To use a different folder, start QualFrame from a terminal with `qualframe start --workspace PATH`, or set the `QUALFRAME_HOME` environment variable.

## 2. Look around the demo

On the home page, choose **Open the demo study**. It contains six fictional interviews from two fictional clinics about adopting an AI documentation assistant, an original 15-code codebook, and coding runs by Claude Sonnet 5.5 and GPT-6.1 Sol, replayed from recordings made in October 2026, so you can see real model output and compare two models. Nothing is sent anywhere.

Enter your name when asked. It is recorded with your decisions and only asked once.

Then follow the steps in the left-hand panel:

- **Review** shows one proposal at a time. The passage is highlighted in the transcript, and the code's definition and guidance are on the right. Press **A** to accept, **R** to reject, **L** to leave it for later, and **C** to change the code. To change the passage, select different text in the transcript and press **U**. **J** and **K** move to the next and previous proposal.
- **Results** appears once a transcript is fully reviewed. It shows how many passages you kept for each code in each transcript; select a number to read the passages. **Export to Excel** saves the reviewed coding.
- **Compare runs** sets the demo's two runs side by side and lists the passages only one of them coded.

## 3. Start your own study

Choose **New study** at the top of the page.

1. **Name and data type.** Pick *De-identified* or *Sensitive* for real interviews. *Test or synthetic data* unlocks the offline test models and is meant for trying things out.
2. **Sources.** Drag your transcripts onto the page. Word (.docx) and plain text (.txt) are supported, up to 25 MB each. Give a site or group name if you want to compare groups later. Transcripts are copied into the study; your originals are never changed.
3. **Codebook.** Import an Excel workbook. You'll choose the sheet and header row, then match columns to **code ID**, **code name**, **definition**, and optionally **parent code ID**, **include** and **exclude** guidance, and **examples**. You can check the codes before anything is saved. The [example codebook](../demo/datasets/ai-scribe/codebook.xlsx) shows a layout that maps automatically.
4. **Run coding.** Choose a model. For a hosted model, paste your API key, set a spending limit, and confirm that your approvals allow sending transcripts to that provider. The page shows how many requests will be sent and an estimated cost before you start. See [Models and data](models-and-data.md) for help choosing.
5. **Review** each proposal, then open **Results**.

## 4. Writing it up

[Reporting QualFrame in your methods](reporting.md) lists what to report and gives a template paragraph. Everything it mentions is in the study folder: the exact prompt, model and settings for each run, the codebook version, and every review decision with its date and reviewer.

## Troubleshooting

- **The browser didn't open.** Go to `http://127.0.0.1:8765` yourself.
- **Another program uses port 8765.** QualFrame picks the next free port and prints the address in the start window. If QualFrame is already running, starting it again just opens the existing window.
- **A run stopped part-way.** Open **Run details** for that run. Requests that finished are kept, and you can resume. If a provider request failed, QualFrame does not retry automatically, so it never pays twice without asking you.
- **"Exact quotation is missing or occurs more than once."** The model's quote doesn't match the transcript exactly, or matches more than one place. Select the right passage in the transcript and press **U**, or reject the proposal.
