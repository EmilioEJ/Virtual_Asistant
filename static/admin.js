const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const fileList = document.getElementById('fileList');
const uploadBtn = document.getElementById('uploadBtn');
const uploadSection = document.getElementById('uploadSection');
const progressContainer = document.getElementById('progressContainer');
const progressFill = document.getElementById('progressFill');
const terminalLogs = document.getElementById('terminalLogs');
const dbStatusText = document.getElementById('dbStatusText');
const dbBadge = document.getElementById('dbBadge');

let selectedFiles = [];
let pollingInterval = null;

// --- Funciones Iniciales ---
async function fetchStatus() {
    try {
        const res = await fetch('/api/admin/rag_status');
        const data = await res.json();
        
        dbStatusText.textContent = data.docs_in_db > 0 
            ? "Base de conocimiento activa y lista." 
            : "No hay documentos cargados en la memoria.";
        dbBadge.textContent = data.docs_in_db + " Fragmentos";

        if (data.is_processing) {
            showProgressUI();
            updateProgress(data);
            if (!pollingInterval) {
                pollingInterval = setInterval(fetchStatus, 1000);
            }
        } else if (pollingInterval) {
            // Acaba de terminar el procesamiento
            clearInterval(pollingInterval);
            pollingInterval = null;
            updateProgress(data);
            setTimeout(() => {
                alert("¡Procesamiento RAG completado!");
                window.location.reload();
            }, 500);
        }
    } catch (e) {
        console.error("Error fetching status", e);
    }
}

fetchStatus();

// --- Drag & Drop ---
dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    handleFiles(e.dataTransfer.files);
});

fileInput.addEventListener('change', (e) => {
    handleFiles(e.target.files);
});

function handleFiles(files) {
    for (let file of files) {
        if (file.type === "application/pdf") {
            // Evitar duplicados por nombre
            if (!selectedFiles.some(f => f.name === file.name)) {
                selectedFiles.push(file);
            }
        } else {
            alert(`El archivo ${file.name} no es un PDF.`);
        }
    }
    renderFileList();
}

function renderFileList() {
    fileList.innerHTML = '';
    selectedFiles.forEach((file, index) => {
        const badge = document.createElement('div');
        badge.className = 'file-badge';
        badge.innerHTML = `📄 ${file.name} <span style="cursor:pointer; margin-left:5px" onclick="removeFile(${index})">❌</span>`;
        fileList.appendChild(badge);
    });

    uploadBtn.disabled = selectedFiles.length === 0;
}

window.removeFile = function(index) {
    selectedFiles.splice(index, 1);
    renderFileList();
}

// --- Upload Process ---
uploadBtn.addEventListener('click', async () => {
    if (selectedFiles.length === 0) return;

    if (!confirm("Al iniciar este proceso, la base de datos anterior se borrará y se reemplazará con estos " + selectedFiles.length + " archivo(s). ¿Continuar?")) {
        return;
    }

    const formData = new FormData();
    selectedFiles.forEach(file => {
        formData.append("files", file);
    });

    try {
        uploadBtn.disabled = true;
        const res = await fetch('/api/admin/upload_docs', {
            method: 'POST',
            body: formData
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Error subiendo archivos");
        }

        showProgressUI();
        pollingInterval = setInterval(fetchStatus, 1000);
    } catch (e) {
        alert("Error: " + e.message);
        uploadBtn.disabled = false;
    }
});

function showProgressUI() {
    uploadSection.style.display = 'none';
    progressContainer.style.display = 'flex';
}

function updateProgress(data) {
    progressFill.style.width = data.progress_percent + '%';
    
    // Render logs
    if (data.logs && data.logs.length > 0) {
        terminalLogs.innerHTML = data.logs.map(log => `<p>> ${log}</p>`).join('');
        // Auto scroll to bottom
        terminalLogs.scrollTop = terminalLogs.scrollHeight;
    }
}
