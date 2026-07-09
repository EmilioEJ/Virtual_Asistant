#!/bin/bash
rsync -az -e "ssh -o BatchMode=yes -o StrictHostKeyChecking=no" --exclude '.venv' --exclude '__pycache__' --exclude '.git' --exclude 'docs_temp' /home/emilioej/EmilioEJ/Asistente_Virtual/ eespinozajimenez@63.141.255.7:~/Asistente_Virtual/
