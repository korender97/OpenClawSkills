Basis-Befehl zum Senden einer E-Mail
gog send \
  --to empfaenger@email.com \
  --subject "Betreff" \
  --body "Nachricht"
  

Email mit Datei-Inhalt
gog send \
  --to empfaenger@email.com \
  --subject "Report" \
  --body-file ./message.txt
  

Email mit Anhang
gog send \
  --to empfaenger@email.com \
  --subject "Datei" \
  --body "Siehe Anhang" \
  --attach ./file.pdf
  

👥 Mehrere Empfänger
gog send \
  --to a@mail.com,b@mail.com \
  --subject "Test" \
  --body "Hallo zusammen"
