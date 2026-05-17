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
    'models/avatar.vrm?v=' + Date.now(), // Cache-buster para que siempre cargue el avatar más nuevo
    (gltf) => {
        const vrm = gltf.userData.vrm;
        // IMPORTANTE: Se eliminó removeUnnecessaryJoints porque rompe la malla (mesh)
        // de la ropa como suéteres (SpringBones) en algunos avatares.
        scene.add(vrm.scene);
        currentVrm = vrm;

        // El avatar mira la cámara
        vrm.scene.rotation.y = Math.PI;

        // --- POSTURA NATURAL (Modificar T-Pose) ---
        const leftUpperArm = vrm.humanoid.getNormalizedBoneNode('leftUpperArm');
        const rightUpperArm = vrm.humanoid.getNormalizedBoneNode('rightUpperArm');
        const leftLowerArm = vrm.humanoid.getNormalizedBoneNode('leftLowerArm');
        const rightLowerArm = vrm.humanoid.getNormalizedBoneNode('rightLowerArm');

        if (leftUpperArm && rightUpperArm) {
            // Un ángulo un poco más abierto para que la ropa no se atraviese con el torso
            leftUpperArm.rotation.z = 1.1;
            rightUpperArm.rotation.z = -1.1;
        }
        if (leftLowerArm && rightLowerArm) {
            leftLowerArm.rotation.x = -0.2;
            rightLowerArm.rotation.x = -0.2;
        }
    },
    (progress) => console.log('Cargando Avatar...', Math.round(100.0 * (progress.loaded / progress.total)), '%'),
    (error) => {
        console.error('No se encontró "models/avatar.vrm". Ponlo en su lugar para cargar el avatar 3D.', error);
        document.querySelector('.camera-status').textContent = "ERROR: AVATAR NO ENCONTRADO";
        document.querySelector('.camera-status').style.color = "red";
    }
);

// Variables para el Lip-Sync (Sincronización de Labios)
let audioContext = null;
let analyser = null;
let dataArray = null;

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
                if(currentVrm) currentVrm.expressionManager.setValue('blink', 0.0);
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
        if (head) {
            head.rotation.y = Math.sin(time * 0.7) * 0.01;   // Cabeza siguiendo el balanceo
            head.rotation.z = Math.cos(time * 0.5) * 0.01;   // Ligero ladeo de la cabeza
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

async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;

    addMessage(text, true);
    userInput.value = '';
    showLoading();

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        });

        const data = await response.json();

        if (response.ok) {
            // En vez de mostrar el texto rápido, esperamos a sincronizar el audio
            await speakTextAndShow(data.reply);
        } else {
            removeLoading();
            addMessage('Error: ' + (data.detail || 'Problema de conexión.'));
        }
    } catch (error) {
        removeLoading();
        addMessage('Error de red al conectar con el servidor.');
    }
}

// Enviar evento invisible al chat
async function sendHiddenEvent(hiddenPrompt) {
    showLoading();
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: hiddenPrompt })
        });
        const data = await response.json();
        if (response.ok) {
            await speakTextAndShow(data.reply);
        } else {
            removeLoading();
        }
    } catch (e) {
        removeLoading();
    }
}
sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
});

// 2.1 Text-to-Speech Sincronizado (El VRM Habla)
async function speakTextAndShow(text) {
    let cleanText = text.replace(/[*#_]/g, '').trim();
    if (!cleanText) {
        removeLoading();
        addMessage(text, false);
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
            body: JSON.stringify({ message: cleanText })
        });

        if (!response.ok) {
            removeLoading();
            addMessage(text, false);
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

        audio.onplay = () => { isSpeaking = true; };
        audio.onended = () => {
            isSpeaking = false;
            if (currentVrm) {
                currentVrm.expressionManager.setValue('aa', 0);
                currentVrm.expressionManager.setValue('happy', 0);
            }
        };

        // ---> Sincronización <---
        // Eliminamos el indicador de carga y mostramos el mensaje JUSTO antes de reproducir el audio
        removeLoading();
        addMessage(text, false);
        await audio.play();

    } catch (err) {
        console.error("Error conectando con la voz neuronal:", err);
        removeLoading();
        addMessage(text, false);
    }
}

// 2.2 Speech-to-Text (El VRM Escucha)
const micBtn = document.getElementById('micBtn');
let recognition;
if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.lang = 'es-MX';
    recognition.continuous = false;

    recognition.onstart = () => {
        micBtn.classList.add('recording');
        userInput.placeholder = "Escuchando...";
    };

    recognition.onresult = (event) => {
        userInput.value = event.results[0][0].transcript;
        sendMessage();
    };

    recognition.onend = () => {
        micBtn.classList.remove('recording');
        userInput.placeholder = "Escribe o presiona el micrófono...";
    };

    if (micBtn) {
        micBtn.addEventListener('click', () => {
            if (micBtn.classList.contains('recording')) recognition.stop();
            else try { recognition.start(); } catch (e) { }
        });
    }
}

// ==========================================
// 3. WebSockets (Fase Final: OpenCV)
// ==========================================
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);

let hasWelcomed = false;
let wasInterrupted = false;

ws.onopen = () => {
    console.log("Conectado al Ojo (Visión Artificial de OpenCV)");
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
