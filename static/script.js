import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

// ==========================================
// 1. Configuración de Three.js y VRM Avatar
// ==========================================
const container = document.getElementById('canvas-container');
const scene = new THREE.Scene();

// Cámara (Encuadre: Cintura para arriba)
const camera = new THREE.PerspectiveCamera(35, container.clientWidth / container.clientHeight, 0.15, 10);
// Coordenadas: X (Izquierda/Derecha), Y (Arriba/Abajo), Z (Profundidad/Zoom)
// Ajuste para avatares diferentes (se alejó un poco a Z=1.8 y se bajó a Y=1.2)
camera.position.set(0, 1.3, 1.5);

// Renderizador
const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
renderer.setSize(container.clientWidth, container.clientHeight);
renderer.setPixelRatio(window.devicePixelRatio);
container.appendChild(renderer.domElement);

// Luces para el Avatar
const light = new THREE.DirectionalLight(0xffffff, 2.0);
light.position.set(1, 1, 1).normalize();
scene.add(light);
scene.add(new THREE.AmbientLight(0xffffff, 1.5));

let currentVrm = null;

// Cargar el Avatar VRM
const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));

loader.load(
    '/static/models/ARIA.vrm?v=' + Date.now(), // Cache-buster para que siempre cargue el avatar más nuevo
    (gltf) => {
        const vrm = gltf.userData.vrm;
        // IMPORTANTE: Se eliminó removeUnnecessaryJoints porque rompe la malla (mesh)
        // de la ropa como suéteres (SpringBones) en algunos avatares.
        scene.add(vrm.scene);
        currentVrm = vrm;

        // El avatar mira la cámara (ajuste para el nuevo modelo)
        vrm.scene.rotation.y = 0;

        // --- POSTURA NATURAL (Modificar T-Pose) ---
        const leftUpperArm = vrm.humanoid.getNormalizedBoneNode('leftUpperArm');
        const rightUpperArm = vrm.humanoid.getNormalizedBoneNode('rightUpperArm');
        const leftLowerArm = vrm.humanoid.getNormalizedBoneNode('leftLowerArm');
        const rightLowerArm = vrm.humanoid.getNormalizedBoneNode('rightLowerArm');

        if (leftUpperArm && rightUpperArm) {
            // Brazos descansando naturalmente pegados al cuerpo y un poco hacia adelante
            leftUpperArm.rotation.set(0.1, -0.15, -1.25);
            rightUpperArm.rotation.set(0.1, 0.15, 1.25);
        }
        if (leftLowerArm && rightLowerArm) {
            // Codos flexionados ligeramente hacia el frente para no verse tiesos
            leftLowerArm.rotation.set(-0.25, -0.1, 0);
            rightLowerArm.rotation.set(-0.25, 0.1, 0);
        }

        // --- POSTURA NATURAL DE LAS MANOS (Curvar dedos y relajar muñecas) ---
        const leftHand = vrm.humanoid.getNormalizedBoneNode('leftHand');
        const rightHand = vrm.humanoid.getNormalizedBoneNode('rightHand');
        // Dejar las muñecas en 0 para evitar que las palmas miren hacia arriba
        if (leftHand) leftHand.rotation.set(0, 0, 0);
        if (rightHand) rightHand.rotation.set(0, 0, 0);

        const fingers = ['Index', 'Middle', 'Ring', 'Little'];
        fingers.forEach((finger, index) => {
            // El dedo índice se curva menos, el meñique más
            const curlAmount = 0.3 + (index * 0.05); 
            
            ['Proximal', 'Intermediate', 'Distal'].forEach(joint => {
                const lFinger = vrm.humanoid.getNormalizedBoneNode(`left${finger}${joint}`);
                const rFinger = vrm.humanoid.getNormalizedBoneNode(`right${finger}${joint}`);
                
                // Flexión principal (cerrar la mano ligeramente, signos invertidos para evitar hiperextensión)
                if (lFinger) lFinger.rotation.z = -curlAmount;
                if (rFinger) rFinger.rotation.z = curlAmount;
                
                // Evitar que estén muy separados (Splay)
                if (lFinger) lFinger.rotation.x = 0;
                if (rFinger) rFinger.rotation.x = 0;
            });
        });

        // Pulgar (Thumb)
        ['Proximal', 'Intermediate', 'Distal'].forEach(joint => {
            const lThumb = vrm.humanoid.getNormalizedBoneNode(`leftThumb${joint}`);
            const rThumb = vrm.humanoid.getNormalizedBoneNode(`rightThumb${joint}`);
            if (lThumb) { lThumb.rotation.y = -0.3; lThumb.rotation.z = -0.2; }
            if (rThumb) { rThumb.rotation.y = 0.3; rThumb.rotation.z = 0.2; }
        });
    },
    (progress) => console.log('Cargando Avatar...', Math.round(100.0 * (progress.loaded / progress.total)), '%'),
    (error) => {
        console.error('No se encontró "models/ARIA.vrm". Ponlo en su lugar para cargar el avatar 3D.', error);
        document.querySelector('.camera-status').textContent = "ERROR: AVATAR NO ENCONTRADO";
        document.querySelector('.camera-status').style.color = "red";
    }
);

// Variables para el Lip-Sync (Sincronización de Labios)
let audioContext = null;
let analyser = null;
let dataArray = null;

// Variables para el seguimiento del ratón
let mouseX = 0;
let mouseY = 0;
document.addEventListener('mousemove', (event) => {
    // Normalizar coordenadas a rango [-1, 1]
    mouseX = (event.clientX / window.innerWidth) * 2 - 1;
    mouseY = -(event.clientY / window.innerHeight) * 2 + 1;
});

const clock = new THREE.Clock();
let currentMouthOpen = 0; // Para suavizar el movimiento de la boca
let nextBlinkTime = 0; // Para el parpadeo aleatorio

function animate() {
    requestAnimationFrame(animate);
    const deltaTime = clock.getDelta();
    const time = clock.elapsedTime; // Tiempo global

    if (currentVrm) {
        currentVrm.update(deltaTime);

        // 1. Parpadeo Natural Orgánico
        if (time > nextBlinkTime) {
            currentVrm.expressionManager.setValue('blink', 1.0);
            setTimeout(() => {
                if (currentVrm) currentVrm.expressionManager.setValue('blink', 0.0);
            }, 150); // Cierra los ojos por 150ms
            nextBlinkTime = time + 2 + Math.random() * 4; // Siguiente parpadeo en 2 a 6 segundos
        }

        // 2. Movimiento Corporal Orgánico (Respiración y Balanceo)
        const spine = currentVrm.humanoid.getNormalizedBoneNode('spine');
        const head = currentVrm.humanoid.getNormalizedBoneNode('head');
        if (spine) {
            spine.rotation.x = Math.sin(time * 1.5) * 0.015; // Pecho inflándose (respiración)
            spine.rotation.y = Math.sin(time * 0.7) * 0.02;  // Balanceo del torso
        }
        // Offset para centrar la mirada en la nariz en vez del centro de la pantalla
        const offsetX = 0.0;
        const offsetY = 0.55; // Nivel de la cara en la ventana (ajusta si es necesario)

        if (head) {
            // Mirar al frente (sin seguimiento del ratón) + balanceo natural
            const targetHeadY = Math.sin(time * 0.7) * 0.01;
            const targetHeadX = 0;
            
            head.rotation.y += (targetHeadY - head.rotation.y) * 0.1;
            head.rotation.x += (targetHeadX - head.rotation.x) * 0.1;
            head.rotation.z = Math.cos(time * 0.5) * 0.01;   // Ligero ladeo de la cabeza
        }
        
        // 2.5 Ojos siguiendo el ratón
        const leftEye = currentVrm.humanoid.getNormalizedBoneNode('leftEye');
        const rightEye = currentVrm.humanoid.getNormalizedBoneNode('rightEye');
        if (leftEye && rightEye) {
            // Mirar al frente (sin seguimiento del ratón)
            const targetEyeY = 0;
            const targetEyeX = 0;
            
            leftEye.rotation.y += (targetEyeY - leftEye.rotation.y) * 0.2;
            leftEye.rotation.x += (targetEyeX - leftEye.rotation.x) * 0.2;
            rightEye.rotation.y += (targetEyeY - rightEye.rotation.y) * 0.2;
            rightEye.rotation.x += (targetEyeX - rightEye.rotation.x) * 0.2;
        }

        // 3. Lip-Sync Suavizado (Sin afectar los ojos)
        // Eliminamos 'happy' y 'ih' porque en algunos modelos VRM están vinculados a los párpados
        let targetMouthOpen = 0;
        if (analyser && dataArray && isSpeaking) {
            analyser.getByteFrequencyData(dataArray);
            let volume = 0;
            for (let i = 0; i < dataArray.length; i++) {
                volume += dataArray[i];
            }
            volume = volume / dataArray.length; // Promedio

            // Si hay volumen, calculamos la apertura de forma no lineal
            if (volume > 2) {
                targetMouthOpen = Math.min((volume / 40) * 1.2, 0.9);
            }
        }

        // Suavizado matemático (Lerp) para quitar el temblor robótico
        currentMouthOpen += (targetMouthOpen - currentMouthOpen) * 0.35;

        // Solo usamos vocales directas para evitar deformar los ojos
        currentVrm.expressionManager.setValue('aa', currentMouthOpen * 0.85);
        currentVrm.expressionManager.setValue('ou', currentMouthOpen * 0.15); // Un toque de redondez
        
        // 4. Movimiento Orgánico de Brazos y Ropa (SpringBones)
        const leftUpperArm = currentVrm.humanoid.getNormalizedBoneNode('leftUpperArm');
        const rightUpperArm = currentVrm.humanoid.getNormalizedBoneNode('rightUpperArm');
        const leftLowerArm = currentVrm.humanoid.getNormalizedBoneNode('leftLowerArm');
        const rightLowerArm = currentVrm.humanoid.getNormalizedBoneNode('rightLowerArm');
        const hips = currentVrm.humanoid.getNormalizedBoneNode('hips');

        if (hips) {
            // Balanceo pélvico sutil para forzar a que las físicas (SpringBones) de la ropa se muevan continuamente
            hips.rotation.y = Math.sin(time * 0.8) * 0.03;
            hips.rotation.z = Math.cos(time * 0.6) * 0.015;
            // (Eliminamos la modificación de hips.position.y para no arruinar la altura natural del VRM)
        }

        if (leftUpperArm && rightUpperArm) {
            // Respiración natural reflejada en hombros y brazos
            leftUpperArm.rotation.x = 0.1 + Math.sin(time * 1.5) * 0.02;
            rightUpperArm.rotation.x = 0.1 + Math.cos(time * 1.5) * 0.02;
            leftUpperArm.rotation.z = -1.25 + Math.sin(time * 1.2) * 0.03;
            rightUpperArm.rotation.z = 1.25 + Math.cos(time * 1.2) * 0.03;
            
            if (leftLowerArm && rightLowerArm) {
                // Relajación de codos oscilante
                leftLowerArm.rotation.x = -0.25 + Math.sin(time * 0.9) * 0.04;
                rightLowerArm.rotation.x = -0.25 + Math.cos(time * 0.9) * 0.04;
            }
        }
    }

    // Enfocar cámara al nivel del pecho/abdomen superior
    // Se bajó a 0.8 para centrar el cuerpo y no cortar la cintura
    camera.lookAt(0, 1.2, 0);
    renderer.render(scene, camera);
}
animate();

window.addEventListener('resize', () => {
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
});


// ==========================================
// 2. Lógica del Chat y TTS Neural
// ==========================================
const chatBox = document.getElementById('chatBox');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
let isSpeaking = false;
let currentAudio = null; // Guardar referencia al audio actvo para interrumpirlo

function addMessage(text, isUser = false) {
    const msgDiv = document.createElement('div');
    msgDiv.classList.add('message');
    msgDiv.classList.add(isUser ? 'user-msg' : 'system-msg');
    let formattedText = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    msgDiv.innerHTML = `<p>${formattedText}</p>`;
    chatBox.appendChild(msgDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function showLoading() {
    const loadingDiv = document.createElement('div');
    loadingDiv.classList.add('loading-msg');
    loadingDiv.id = 'loadingIndicator';
    loadingDiv.innerHTML = `<div class="dot"></div><div class="dot"></div><div class="dot"></div>`;
    chatBox.appendChild(loadingDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function removeLoading() {
    const loadingDiv = document.getElementById('loadingIndicator');
    if (loadingDiv) loadingDiv.remove();
}

let currentMode = "conversational"; // "chat" o "conversational"

async function sendMessage(textToSend = null) {
    const text = textToSend !== null ? textToSend : userInput.value.trim();
    if (!text) return;

    if (currentMode === "chat") {
        addMessage(text, true);
        userInput.value = '';
        showLoading();
    } else {
        // En modo conversacional, animamos las ondas para indicar que la IA está pensando
        document.getElementById('convStatus').textContent = "Aria está pensando...";
        document.getElementById('convWaves').classList.add('active');
    }

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, mode: currentMode })
        });

        const data = await response.json();

        if (response.ok) {
            // En vez de mostrar el texto rápido, esperamos a sincronizar el audio
            await speakTextAndShow(data.reply);
        } else {
            if (currentMode === "chat") {
                removeLoading();
                addMessage('Error: ' + (data.detail || 'Problema de conexión.'));
            } else {
                document.getElementById('convStatus').textContent = "Error de conexión";
                document.getElementById('convWaves').classList.remove('active');
            }
        }
    } catch (error) {
        if (currentMode === "chat") {
            removeLoading();
            addMessage('Error de red al conectar con el servidor.');
        } else {
            document.getElementById('convStatus').textContent = "Error de red";
            document.getElementById('convWaves').classList.remove('active');
        }
    }
}

// Enviar evento invisible al chat
async function sendHiddenEvent(hiddenPrompt) {
    if (currentMode === "chat") showLoading();
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: hiddenPrompt, mode: currentMode })
        });
        const data = await response.json();
        if (response.ok) {
            await speakTextAndShow(data.reply);
        } else {
            if (currentMode === "chat") removeLoading();
        }
    } catch (e) {
        if (currentMode === "chat") removeLoading();
    }
}
sendBtn.addEventListener('click', () => sendMessage(null));
userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage(null);
});

// 2.1 Text-to-Speech Sincronizado (El VRM Habla)
async function speakTextAndShow(text) {
    let cleanText = text.replace(/[*#_]/g, '').trim();
    if (!cleanText) {
        if (currentMode === "chat") {
            removeLoading();
            addMessage(text, false);
        } else {
            document.getElementById('convStatus').textContent = "Toca el micrófono para hablar con Aria";
            document.getElementById('convWaves').classList.remove('active');
        }
        return;
    }

    // INTERRUPCIÓN DE VOZ: Detener el audio si ya hay alguien hablando
    if (currentAudio) {
        currentAudio.pause();
        currentAudio.currentTime = 0;
        currentAudio = null;
        isSpeaking = false;
        if (currentVrm) {
            currentVrm.expressionManager.setValue('aa', 0);
            currentVrm.expressionManager.setValue('happy', 0);
        }
    }

    try {
        const response = await fetch('/api/tts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: cleanText, mode: currentMode })
        });

        if (!response.ok) {
            if (currentMode === "chat") {
                removeLoading();
                addMessage(text, false);
            } else {
                document.getElementById('convStatus').textContent = "Error reproduciendo voz";
                document.getElementById('convWaves').classList.remove('active');
            }
            return;
        }

        const audioBlob = await response.blob();
        const audioUrl = URL.createObjectURL(audioBlob);

        if (!audioContext) audioContext = new (window.AudioContext || window.webkitAudioContext)();

        const audio = new Audio(audioUrl);
        currentAudio = audio; // Guardar referencia global

        const source = audioContext.createMediaElementSource(audio);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        dataArray = new Uint8Array(analyser.frequencyBinCount);

        source.connect(analyser);
        analyser.connect(audioContext.destination);

        audio.onplay = () => { 
            isSpeaking = true; 
            if (currentMode === "conversational") {
                document.getElementById('convStatus').textContent = "Aria está hablando...";
            }
        };
        audio.onended = () => {
            isSpeaking = false;
            if (currentVrm) {
                currentVrm.expressionManager.setValue('aa', 0);
                currentVrm.expressionManager.setValue('happy', 0);
            }
            if (currentMode === "conversational") {
                document.getElementById('convStatus').textContent = "Toca el micrófono para hablar con Aria";
                document.getElementById('convWaves').classList.remove('active');
            }
        };

        // ---> Sincronización <---
        if (currentMode === "chat") {
            removeLoading();
            addMessage(text, false);
        }
        await audio.play();

    } catch (err) {
        console.error("Error conectando con la voz neuronal:", err);
        if (currentMode === "chat") {
            removeLoading();
            addMessage(text, false);
        } else {
            document.getElementById('convStatus').textContent = "Toca el micrófono para hablar con Aria";
            document.getElementById('convWaves').classList.remove('active');
        }
    }
}

// 2.2 Speech-to-Text (El VRM Escucha)
// 2.2 Speech-to-Text (MediaRecorder -> Backend Groq Whisper)
const micBtn = document.getElementById('micBtn');
const bigMicBtn = document.getElementById('bigMicBtn');

let mediaRecorder = null;
let audioChunks = [];
let isRecordingAudio = false;

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];

        mediaRecorder.ondataavailable = event => {
            if (event.data.size > 0) audioChunks.push(event.data);
        };

        mediaRecorder.onstart = () => {
            isRecordingAudio = true;
            if (currentMode === "chat") {
                micBtn.classList.add('recording');
                userInput.placeholder = "Escuchando...";
            } else {
                bigMicBtn.classList.add('listening');
                document.getElementById('convStatus').textContent = "Escuchando...";
                document.getElementById('convWaves').classList.remove('active');
            }
        };

        mediaRecorder.onstop = async () => {
            isRecordingAudio = false;
            // Detener el uso del micrófono
            mediaRecorder.stream.getTracks().forEach(t => t.stop());

            if (currentMode === "chat") {
                micBtn.classList.remove('recording');
                userInput.placeholder = "Transcribiendo...";
            } else {
                bigMicBtn.classList.remove('listening');
                document.getElementById('convStatus').textContent = "Transcribiendo audio...";
            }

            const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            await sendAudioToBackend(audioBlob);
        };

        mediaRecorder.start();

    } catch (err) {
        console.error("Error al acceder al micrófono:", err);
        alert("Permiso de micrófono denegado o dispositivo no encontrado.");
    }
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
    }
}

async function sendAudioToBackend(audioBlob) {
    const formData = new FormData();
    // Le ponemos extensión .webm para que Whisper lo reconozca
    formData.append("audio", audioBlob, "grabacion.webm");

    try {
        const response = await fetch('/api/stt', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) throw new Error("Error en el servidor STT");

        const data = await response.json();
        const text = data.text.trim();

        if (text) {
            if (currentMode === "chat") {
                userInput.value = text;
                sendMessage(null);
            } else {
                sendMessage(text);
            }
        } else {
            if (currentMode === "chat") {
                userInput.placeholder = "No se detectó voz.";
            } else {
                document.getElementById('convStatus').textContent = "No se detectó voz.";
            }
        }
    } catch (error) {
        console.error("Error transcribiendo el audio:", error);
        alert("Error al transcribir el audio. ¿Está configurado Groq en el .env?");
        if (currentMode === "chat") {
            userInput.placeholder = "Escribe o presiona el micrófono...";
        } else {
            document.getElementById('convStatus').textContent = "Toca el micrófono para hablar con Aria";
        }
    }
}

function handleMicClick() {
    if (isRecordingAudio) {
        stopRecording();
    } else {
        startRecording();
    }
}

if (micBtn) micBtn.addEventListener('click', handleMicClick);
if (bigMicBtn) bigMicBtn.addEventListener('click', handleMicClick);


// ==========================================
// 2.3 UI Mode Toggler
// ==========================================
const modeChatBtn = document.getElementById('modeChatBtn');
const modeConvBtn = document.getElementById('modeConvBtn');
const chatModeContainer = document.getElementById('chatModeContainer');
const convModeContainer = document.getElementById('convModeContainer');

modeChatBtn.addEventListener('click', () => {
    currentMode = "chat";
    modeChatBtn.classList.add('active');
    modeConvBtn.classList.remove('active');
    chatModeContainer.classList.add('active-mode');
    chatModeContainer.classList.remove('hidden-mode');
    convModeContainer.classList.remove('active-mode');
    convModeContainer.classList.add('hidden-mode');
});

modeConvBtn.addEventListener('click', () => {
    currentMode = "conversational";
    modeConvBtn.classList.add('active');
    modeChatBtn.classList.remove('active');
    convModeContainer.classList.add('active-mode');
    convModeContainer.classList.remove('hidden-mode');
    chatModeContainer.classList.remove('active-mode');
    chatModeContainer.classList.add('hidden-mode');
});

// ==========================================
// 3. WebSockets (Fase Final: OpenCV)
// ==========================================
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);

let hasWelcomed = false;
let wasInterrupted = false;

// ==========================================
// 4. Captura de Video para Visión Artificial en Backend
// ==========================================
let videoElement = document.createElement('video');
videoElement.autoplay = true;
videoElement.style.display = 'none';
document.body.appendChild(videoElement);

let canvasElement = document.createElement('canvas');
canvasElement.style.display = 'none';
document.body.appendChild(canvasElement);
let ctx = canvasElement.getContext('2d');

let isCameraActive = false;

async function startCameraForVision() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true });
        videoElement.srcObject = stream;
        
        videoElement.onloadedmetadata = () => {
            canvasElement.width = 320; // Resolución fija baja para no saturar la red
            canvasElement.height = 240;
            isCameraActive = true;
            
            // Enviar un frame al backend cada segundo (1000ms)
            setInterval(() => {
                if (ws.readyState === WebSocket.OPEN && isCameraActive) {
                    ctx.drawImage(videoElement, 0, 0, canvasElement.width, canvasElement.height);
                    // Obtener base64 JPG
                    const base64Frame = canvasElement.toDataURL('image/jpeg', 0.5);
                    ws.send(base64Frame);
                }
            }, 1000);
        };
    } catch (err) {
        console.error("Error al acceder a la cámara para visión:", err);
        const sysStatus = document.querySelector('.camera-status');
        if (sysStatus) sysStatus.textContent = 'Permiso de cámara denegado';
    }
}

ws.onopen = () => {
    console.log("Conectado al Ojo (Visión Artificial de OpenCV en servidor)");
    startCameraForVision();
};

ws.onmessage = (event) => {
    const action = event.data;
    const sysStatus = document.querySelector('.camera-status');

    if (action === "person_arrived") {
        if (sysStatus) {
            sysStatus.textContent = '✅ Usuario detectado en cámara';
            sysStatus.style.color = '#00ffaa';
        }

        if (!hasWelcomed) {
            hasWelcomed = true;
            // Saludo inicial exacto solicitado, directo al sistema de voz (ahorra cuota de Gemini)
            speakTextAndShow("Parece que tenemos una visita. Hola, bienvenido a nuestra sesión de información sobre la carrera de Ingeniería en Tecnologías de la Información. Mi nombre es Aria, y estoy aquí para ayudarte con cualquier pregunta que tengas sobre nuestra carrera. ¿En qué puedo ayudarte hoy?");
        } else {
            if (wasInterrupted) {
                wasInterrupted = false;
                sendHiddenEvent("(Sistema: El usuario acaba de volver a la cámara después de irse ABRUPTAMENTE mientras le hablabas. Sé empático, ofrécele una disculpa si te extendiste o pregúntale si quiere que repitas/resumas la información que le estabas dando.)");
            } else {
                sendHiddenEvent("(Sistema: El usuario acaba de volver a la cámara después de haberse ido en silencio. Dile algo como '¡Qué bueno que regresas!' o indícale que estás aquí para continuar.)");
            }
        }
    }
    else if (action === "person_left") {
        if (sysStatus) {
            sysStatus.textContent = '⚠️ Usuario se fue...';
            sysStatus.style.color = '#ffaa00';
        }

        if (isSpeaking) {
            wasInterrupted = true;
            sendHiddenEvent("(Sistema: El usuario se acaba de ir de la cámara INTERRUMPIENDO de tajo lo que estabas explicando. Deja de hablar de la carrera inmediatamente, pausa y di algo MUY breve como 'Uy, veo que tuviste que irte...' o 'Te espero a que vuelvas para seguir explicándote'.)");
        } else {
            sendHiddenEvent("(Sistema: El usuario se acaba de apartar de la cámara y no lo ves. Pregunta de forma natural si sigue ahí o menciónalo ingenuamente.)");
        }
    }
};

ws.onerror = () => {
    const sysStatus = document.querySelector('.camera-status');
    if (sysStatus) sysStatus.textContent = 'Error de conexión de cámara';
};
