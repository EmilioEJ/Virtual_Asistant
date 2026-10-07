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
    '/static/models/ARIA2.0.vrm?v=' + Date.now(), // Cache-buster para que siempre cargue el avatar más nuevo
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
        console.error('No se encontró "models/ARIA2.0.vrm". Ponlo en su lugar para cargar el avatar 3D.', error);
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
let nextBlinkTime = 0; // Para el parpadeo aleatorio

// ==========================================
// 1.1 Animador del avatar
// Cada articulación persigue su objetivo con un resorte amortiguado (inercia natural),
// el reposo usa ruido suave en lugar de ondas perfectas y los gestos tienen variación.
// ==========================================
// Estados: 'reposo' | 'escuchando' | 'pensando' | 'hablando'
const avatar = { estado: 'reposo', desde: 0, gesto: null, proximoGesto: 0, mirada: { x: 0, y: 0 }, objetivoMirada: { x: 0, y: 0 }, proximaMirada: 0 };

// Ruido suave: suma de senos con frecuencias no múltiplas (no se percibe como un ciclo)
const ruido = (t, semilla) => Math.sin(t * 0.37 + semilla) * 0.5 + Math.sin(t * 0.83 + semilla * 1.7) * 0.3 + Math.sin(t * 1.61 + semilla * 2.3) * 0.2;
const suavizar = (x) => x * x * (3 - 2 * x);

// Resorte críticamente amortiguado por eje (rigidez distinta por articulación = movimiento escalonado)
const resortes = new Map();
function resorte(clave, objetivo, rigidez, dt) {
    let r = resortes.get(clave);
    if (!r) { r = { pos: objetivo, vel: 0 }; resortes.set(clave, r); }
    const amortiguacion = 2 * Math.sqrt(rigidez);
    // Subpasos de 1/60 s: el movimiento es igual aunque el equipo dibuje pocos cuadros por segundo
    const pasos = Math.max(1, Math.ceil(dt / 0.0167));
    const h = dt / pasos;
    for (let i = 0; i < pasos; i++) {
        r.vel += (rigidez * (objetivo - r.pos) - amortiguacion * r.vel) * h;
        r.pos += r.vel * h;
    }
    return r.pos;
}
const RIGIDEZ = { UpperArm: 26, LowerArm: 20, Hand: 16 };

// Pose de reposo de cada hueso [x, y, z]
const POSE_BASE = {
    leftUpperArm: [0.1, -0.15, -1.25], rightUpperArm: [0.1, 0.15, 1.25],
    leftLowerArm: [-0.25, -0.15, 0], rightLowerArm: [-0.25, 0.15, 0],
    leftHand: [0, 0, 0], rightHand: [0, 0, 0],
};

// Gestos: pose objetivo por hueso, apertura de las manos (0 = relajada, 1 = abierta)
// y, opcionalmente, una oscilación. 'mantener' los deja activos mientras dure el estado.
const GESTOS = {
    saludo: { duracion: 3.0, manos: { right: 1 }, pose: {
        rightUpperArm: [0.0, 0.35, 0.35], rightLowerArm: [-0.6, 0.2, -1.75], rightHand: [0, 0, -0.1] },
        oscilar: { hueso: 'rightLowerArm', eje: 2, amplitud: 0.28, frecuencia: 2.2 } },
    explicar: { duracion: 2.4, manos: { right: 0.85 }, pose: {
        rightUpperArm: [-0.35, 0.35, 1.05], rightLowerArm: [-0.2, 1.7, 0], rightHand: [0, 0, 0.15] } },
    explicarIzquierda: { duracion: 2.4, manos: { left: 0.85 }, pose: {
        leftUpperArm: [-0.35, -0.35, -1.05], leftLowerArm: [-0.2, -1.7, 0], leftHand: [0, 0, -0.15] } },
    abrirManos: { duracion: 2.6, manos: { right: 1, left: 1 }, pose: {
        rightUpperArm: [-0.3, 0.3, 1.1], rightLowerArm: [-0.2, 1.55, 0], rightHand: [0, 0, 0.3],
        leftUpperArm: [-0.3, -0.3, -1.1], leftLowerArm: [-0.2, -1.55, 0], leftHand: [0, 0, -0.3] } },
    senalar: { duracion: 2.0, manos: { right: 0.6 }, pose: {
        rightUpperArm: [-0.4, 0.5, 1.0], rightLowerArm: [-0.2, 1.85, 0], rightHand: [0, 0, 0.1] } },
    // Pensar: mano bajo el mentón, mantenida mientras dura el estado
    pensar: { mantener: true, manos: { right: 0.35 }, pose: {
        rightUpperArm: [-0.9, 0.9, 1.1], rightLowerArm: [-0.3, 2.5, 0], rightHand: [0, 0.3, 0.5],
        leftUpperArm: [-0.15, -0.35, -1.15], leftLowerArm: [-0.3, -1.35, 0], leftHand: [0, 0, -0.2] } },
};
const GESTOS_HABLA = ['explicar', 'explicarIzquierda', 'abrirManos', 'senalar'];

function lanzarGesto(nombre, variacion = true) {
    const def = GESTOS[nombre];
    if (!def) return;
    avatar.gesto = {
        nombre, def, inicio: clock.elapsedTime, fin: null,
        duracion: def.mantener ? Infinity : def.duracion * (variacion ? 0.85 + Math.random() * 0.35 : 1),
        intensidad: variacion ? 0.75 + Math.random() * 0.25 : 1,
    };
}
function soltarGesto() {
    if (avatar.gesto && avatar.gesto.duracion === Infinity) {
        avatar.gesto.duracion = clock.elapsedTime - avatar.gesto.inicio + 0.7;
    }
}

function setEstadoAvatar(estado) {
    if (avatar.estado === estado) return;
    if (avatar.estado === 'pensando') soltarGesto();
    avatar.estado = estado;
    avatar.desde = clock.elapsedTime;
    avatar.proximoGesto = clock.elapsedTime + 0.4 + Math.random() * 0.6;
    avatar.proximaMirada = 0;
    if (estado === 'pensando') setTimeout(() => { if (avatar.estado === 'pensando') lanzarGesto('pensar', false); }, 350);
}

function pesoGesto(g, t) {
    const entrada = 0.55, salida = 0.7;
    if (t <= 0 || t >= g.duracion) return 0;
    if (t < entrada) return suavizar(t / entrada);
    if (t > g.duracion - salida) return suavizar((g.duracion - t) / salida);
    return 1;
}

// ==========================================
// 1.2 Lip-sync: forma de la boca según las vocales del texto, apertura según el volumen real
// En español la escritura es casi fonética: a, e, i, o, u -> visemas aa, ee, ih, oh, ou;
// m, b y p cierran los labios.
// ==========================================
const VISEMAS = ['aa', 'ee', 'ih', 'oh', 'ou'];
const VOCAL_A_VISEMA = { a: 'aa', e: 'ee', i: 'ih', o: 'oh', u: 'ou', y: 'ih' };
const MAX_VISEMA = { aa: 0.9, ee: 0.65, ih: 0.6, oh: 0.85, ou: 0.75 };
const labios = {
    letras: [], pesoBoca: {}, apertura: 0, buffer: null,
    preparar(texto) {
        // Línea de tiempo por carácter con la misma ponderación que los subtítulos (pausas en la puntuación)
        const limpio = texto.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
        const pesos = [...limpio].map(c => /[.!?:]/.test(c) ? 6 : /[,;]/.test(c) ? 3 : 1);
        const total = pesos.reduce((a, b) => a + b, 0) || 1;
        let acumulado = 0;
        this.letras = [...limpio].map((c, i) => { const l = { c, inicio: acumulado / total }; acumulado += pesos[i]; return l; });
    },
    visemaEn(progreso) {
        if (!this.letras.length) return { visema: 'aa', cerrar: false };
        let i = 0, lo = 0, hi = this.letras.length - 1;
        while (lo <= hi) { const m = (lo + hi) >> 1; if (this.letras[m].inicio <= progreso) { i = m; lo = m + 1; } else hi = m - 1; }
        const c = this.letras[i].c;
        const cerrar = /[mbp]/.test(c);
        for (let d = 0; d < 3; d++) {
            const sig = this.letras[i + d];
            if (sig && VOCAL_A_VISEMA[sig.c]) return { visema: VOCAL_A_VISEMA[sig.c], cerrar };
            if (sig && /[\s.,;:!?]/.test(sig.c)) break;
        }
        if (/[0-9]/.test(c)) return { visema: VISEMAS[Math.floor(progreso * 40) % 3 === 0 ? 0 : 1], cerrar }; // cifras leídas en voz
        return { visema: null, cerrar };
    },
    actualizar(dt) {
        // Volumen RMS del dominio del tiempo (más fiel que el promedio del espectro)
        let nivel = 0;
        if (analyser && isSpeaking) {
            if (!this.buffer || this.buffer.length !== analyser.fftSize) this.buffer = new Float32Array(analyser.fftSize);
            analyser.getFloatTimeDomainData(this.buffer);
            let suma = 0;
            for (let i = 0; i < this.buffer.length; i++) suma += this.buffer[i] * this.buffer[i];
            const rms = Math.sqrt(suma / this.buffer.length);
            nivel = Math.min(Math.max((rms - 0.012) / 0.11, 0), 1);
        }
        // Abre rápido y cierra más despacio, como los labios reales
        const k = nivel > this.apertura ? 0.55 : 0.22;
        this.apertura += (nivel - this.apertura) * k;

        let objetivo = { visema: null, cerrar: false };
        if (currentAudio && isSpeaking && currentAudio.duration && isFinite(currentAudio.duration)) {
            objetivo = this.visemaEn(currentAudio.currentTime / currentAudio.duration);
        }
        const abrir = objetivo.cerrar ? this.apertura * 0.25 : this.apertura;
        for (const v of VISEMAS) {
            const meta = objetivo.visema === v ? abrir * MAX_VISEMA[v] : (objetivo.visema ? 0 : (v === 'aa' ? abrir * 0.6 : 0));
            const actual = this.pesoBoca[v] || 0;
            this.pesoBoca[v] = actual + (meta - actual) * Math.min(1, dt * 18); // coarticulación suave
            if (currentVrm) currentVrm.expressionManager.setValue(v, this.pesoBoca[v]);
        }
        return this.apertura;
    },
};

// Expuesto para depuración desde la consola del navegador
window.ariaAvatar = { gesto: lanzarGesto, estado: setEstadoAvatar, vrm: () => currentVrm, definir: (nombre, def) => { GESTOS[nombre] = def; } };

function animate() {
    requestAnimationFrame(animate);
    const deltaTime = Math.min(clock.getDelta(), 0.25);
    const time = clock.elapsedTime;

    if (currentVrm) {
        const hueso = (nombre) => currentVrm.humanoid.getNormalizedBoneNode(nombre);

        // 0. Boca y energía de la voz
        const voz = labios.actualizar(deltaTime);

        // 1. Parpadeo natural, a veces doble; más frecuente al terminar una frase
        if (time > nextBlinkTime) {
            currentVrm.expressionManager.setValue('blink', 1.0);
            setTimeout(() => { if (currentVrm) currentVrm.expressionManager.setValue('blink', 0.0); }, 120);
            if (Math.random() < 0.2) {
                setTimeout(() => { if (currentVrm) currentVrm.expressionManager.setValue('blink', 1.0); }, 240);
                setTimeout(() => { if (currentVrm) currentVrm.expressionManager.setValue('blink', 0.0); }, 360);
            }
            nextBlinkTime = time + 2.2 + Math.random() * 3.8;
        }

        // 2. Mirada: fijaciones breves con pequeños saltos (sacadas); al pensar, mirada perdida hacia arriba
        if (time > avatar.proximaMirada) {
            if (avatar.estado === 'pensando') {
                avatar.objetivoMirada = { x: -0.14 - Math.random() * 0.05, y: 0.12 + Math.random() * 0.1 };
                avatar.proximaMirada = time + 1.2 + Math.random() * 1.2;
            } else if (avatar.estado === 'escuchando' || Math.random() < 0.6) {
                avatar.objetivoMirada = { x: (Math.random() - 0.5) * 0.02, y: (Math.random() - 0.5) * 0.04 }; // al usuario
                avatar.proximaMirada = time + 1.2 + Math.random() * 2.5;
            } else {
                avatar.objetivoMirada = { x: (Math.random() - 0.5) * 0.08, y: (Math.random() - 0.5) * 0.24 };
                avatar.proximaMirada = time + 0.6 + Math.random() * 1.2;
            }
        }
        avatar.mirada.x += (avatar.objetivoMirada.x - avatar.mirada.x) * Math.min(1, deltaTime * 14);
        avatar.mirada.y += (avatar.objetivoMirada.y - avatar.mirada.y) * Math.min(1, deltaTime * 14);
        const leftEye = hueso('leftEye');
        const rightEye = hueso('rightEye');
        if (leftEye && rightEye) {
            leftEye.rotation.set(avatar.mirada.x, avatar.mirada.y, 0);
            rightEye.rotation.set(avatar.mirada.x, avatar.mirada.y, 0);
        }

        // 3. Cuerpo: respiración, cambio de peso con ruido y postura según el estado
        const spine = hueso('spine');
        const chest = hueso('chest');
        const neck = hueso('neck');
        const head = hueso('head');
        const hips = hueso('hips');
        const respiracion = Math.sin(time * 1.35);
        const inclinacion = avatar.estado === 'escuchando' ? 0.04 : avatar.estado === 'hablando' ? 0.012 : 0;
        if (hips) {
            hips.rotation.y = resorte('hips.y', ruido(time * 0.6, 1) * 0.035, 8, deltaTime);
            hips.rotation.z = resorte('hips.z', ruido(time * 0.35, 2) * 0.025, 8, deltaTime);
        }
        if (spine) {
            spine.rotation.x = resorte('spine.x', respiracion * 0.012 + inclinacion, 10, deltaTime);
            spine.rotation.y = resorte('spine.y', ruido(time * 0.5, 3) * 0.025, 10, deltaTime);
            spine.rotation.z = resorte('spine.z', -ruido(time * 0.35, 2) * 0.02, 10, deltaTime);
        }
        if (chest) chest.rotation.x = Math.sin(time * 1.35 + 0.5) * 0.01;

        if (head) {
            let objX = avatar.mirada.x * 0.4 + ruido(time * 0.7, 4) * 0.015;
            let objY = avatar.mirada.y * 0.5 + ruido(time * 0.5, 5) * 0.025;
            let objZ = ruido(time * 0.4, 6) * 0.025;
            if (avatar.estado === 'escuchando') { objZ += 0.08; objX += 0.035; }
            if (avatar.estado === 'pensando') { objZ -= 0.07; objX -= 0.05; objY += 0.06; }
            if (avatar.estado === 'hablando') {
                objX += voz * 0.05 + Math.sin(time * 4.2) * 0.02 * voz; // acentos de la voz
                objZ += ruido(time * 0.9, 7) * 0.04;
                objY += ruido(time * 0.6, 8) * 0.04;
            }
            head.rotation.x = resorte('head.x', objX, 30, deltaTime);
            head.rotation.y = resorte('head.y', objY, 24, deltaTime);
            head.rotation.z = resorte('head.z', objZ, 18, deltaTime);
            if (neck) neck.rotation.y = head.rotation.y * 0.35;
        }

        // 4. Gestos al hablar, con variación de forma, duración e intensidad
        if (avatar.estado === 'hablando' && !avatar.gesto && time > avatar.proximoGesto && voz > 0.12) {
            const opciones = GESTOS_HABLA.filter(n => n !== avatar.ultimoGesto);
            const nombre = opciones[Math.floor(Math.random() * opciones.length)];
            avatar.ultimoGesto = nombre;
            lanzarGesto(nombre);
            avatar.proximoGesto = time + 2.5 + Math.random() * 3;
        }
        let peso = 0;
        const g = avatar.gesto;
        if (g) {
            const tg = time - g.inicio;
            peso = pesoGesto(g, tg) * g.intensidad;
            if (tg >= g.duracion) avatar.gesto = null;
        }

        // 5. Brazos y manos: objetivo = reposo con ruido + gesto; el resorte da la inercia
        for (const [nombre, base] of Object.entries(POSE_BASE)) {
            const nodo = hueso(nombre);
            if (!nodo) continue;
            const lado = nombre.startsWith('left') ? 1 : -1;
            const tipo = nombre.replace(/^(left|right)/, '');
            const semilla = (lado > 0 ? 10 : 20) + tipo.length;
            const obj = [...base];
            if (tipo === 'UpperArm') {
                obj[0] += respiracion * 0.015 + ruido(time * 0.5, semilla) * 0.025;
                obj[2] += lado * ruido(time * 0.45, semilla + 1) * 0.03;
            } else if (tipo === 'LowerArm') {
                obj[1] += -lado * (ruido(time * 0.55, semilla) * 0.06 + 0.04);
            } else {
                obj[2] += ruido(time * 0.7, semilla) * 0.05;
            }
            const pose = g && g.def.pose[nombre];
            if (pose && peso > 0) {
                for (let i = 0; i < 3; i++) obj[i] += (pose[i] - obj[i]) * peso;
                const osc = g.def.oscilar;
                if (osc && osc.hueso === nombre) {
                    obj[osc.eje] += Math.sin((time - g.inicio) * osc.frecuencia * Math.PI * 2) * osc.amplitud * peso;
                }
            }
            // Movimientos de acento mientras habla: el antebrazo del gesto sube con las sílabas fuertes
            if (pose && tipo === 'LowerArm' && avatar.estado === 'hablando') obj[1] += -lado * voz * 0.12 * peso;
            const k = RIGIDEZ[tipo];
            nodo.rotation.set(
                resorte(nombre + '.x', obj[0], k, deltaTime),
                resorte(nombre + '.y', obj[1], k, deltaTime),
                resorte(nombre + '.z', obj[2], k, deltaTime));
        }

        // 6. Dedos: relajados en reposo, se abren en los gestos, con micromovimiento independiente
        for (const lado of ['left', 'right']) {
            const signo = lado === 'left' ? -1 : 1;
            const apertura = g && g.def.manos && g.def.manos[lado] ? g.def.manos[lado] * peso : 0;
            ['Index', 'Middle', 'Ring', 'Little'].forEach((dedo, i) => {
                const relajado = 0.32 + i * 0.07 + ruido(time * 0.8, i * 3 + (lado === 'left' ? 0 : 50)) * 0.06;
                const abierto = 0.06 + i * 0.03;
                const curva = relajado + (abierto - relajado) * apertura;
                const separacion = (i - 1.5) * 0.06 * apertura;
                ['Proximal', 'Intermediate', 'Distal'].forEach((falange, j) => {
                    const nodo = hueso(`${lado}${dedo}${falange}`);
                    if (!nodo) return;
                    const flexion = resorte(`${lado}${dedo}${falange}`, curva * (1 - j * 0.12), 22, deltaTime);
                    nodo.rotation.set(0, j === 0 ? signo * separacion : 0, signo * flexion);
                });
            });
            ['Proximal', 'Intermediate', 'Distal'].forEach((falange) => {
                const nodo = hueso(`${lado}Thumb${falange}`);
                if (!nodo) return;
                const y = resorte(`${lado}Thumb${falange}`, signo * (0.3 - apertura * 0.15), 22, deltaTime);
                nodo.rotation.set(0, y, signo * 0.2);
            });
        }

        currentVrm.update(deltaTime);
    }

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

function formatearTexto(text) {
    if (typeof marked !== 'undefined') return marked.parse(text);
    return `<p>${text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')}</p>`;
}

function addMessage(text, isUser = false) {
    const msgDiv = document.createElement('div');
    msgDiv.classList.add('message');
    msgDiv.classList.add(isUser ? 'user-msg' : 'system-msg');
    msgDiv.innerHTML = formatearTexto(text);
    chatBox.appendChild(msgDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
    return msgDiv;
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

// ==========================================
// Chat en streaming por WebSocket (/ws/chat)
// ==========================================
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
let chatSocket = null;
let consultaPendiente = null;
let colaChat = Promise.resolve();

function conectarChat() {
    if (chatSocket && chatSocket.readyState === WebSocket.OPEN) return Promise.resolve(chatSocket);
    return new Promise((resolve, reject) => {
        const socket = new WebSocket(`${wsProtocol}//${window.location.host}/ws/chat`);
        socket.onopen = () => { chatSocket = socket; resolve(socket); };
        socket.onerror = () => reject(new Error('No se pudo conectar con el chat.'));
        socket.onclose = () => {
            chatSocket = null;
            if (consultaPendiente) consultaPendiente.reject(new Error('Conexión cerrada.'));
            consultaPendiente = null;
        };
        socket.onmessage = (event) => {
            const datos = JSON.parse(event.data);
            const consulta = consultaPendiente;
            if (!consulta) return;
            if (datos.type === 'token') {
                consulta.onToken(datos.text);
            } else {
                consultaPendiente = null;
                if (datos.type === 'fin') consulta.resolve(datos.reply);
                else consulta.reject(new Error(datos.detail || 'Error del servidor.'));
            }
        };
    });
}

// Las consultas se encadenan para que los fragmentos de una respuesta no se mezclen con la siguiente
function consultarAria(texto, onToken) {
    const resultado = colaChat.then(async () => {
        const socket = await conectarChat();
        return new Promise((resolve, reject) => {
            consultaPendiente = { resolve, reject, onToken };
            socket.send(JSON.stringify({ message: texto }));
        });
    });
    colaChat = resultado.catch(() => {});
    return resultado;
}

// En modo chat el texto aparece a medida que llega; la voz se sintetiza al completar la respuesta
async function responder(texto) {
    let burbuja = null;
    let acumulado = '';
    const reply = await consultarAria(texto, (fragmento) => {
        if (currentMode !== 'chat') return;
        acumulado += fragmento;
        if (!burbuja) {
            removeLoading();
            burbuja = addMessage('', false);
        }
        burbuja.innerHTML = formatearTexto(acumulado);
        chatBox.scrollTop = chatBox.scrollHeight;
    });
    if (burbuja) burbuja.innerHTML = formatearTexto(reply);
    await speakTextAndShow(reply, burbuja !== null);
}

async function sendMessage(textToSend = null) {
    const text = textToSend !== null ? textToSend : userInput.value.trim();
    if (!text) return;
    setEstadoAvatar('pensando');

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
        await responder(text);
    } catch (error) {
        setEstadoAvatar('reposo');
        if (currentMode === "chat") {
            removeLoading();
            addMessage('Error: ' + (error.message || 'Problema de conexión.'));
        } else {
            document.getElementById('convStatus').textContent = "Error de conexión";
            document.getElementById('convWaves').classList.remove('active');
        }
    }
}

// Enviar evento invisible al chat
async function sendHiddenEvent(hiddenPrompt) {
    setEstadoAvatar('pensando');
    if (currentMode === "chat") showLoading();
    try {
        await responder(hiddenPrompt);
    } catch (e) {
        if (currentMode === "chat") removeLoading();
    }
}
sendBtn.addEventListener('click', () => sendMessage(null));
userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage(null);
});

// ==========================================
// Subtítulos: frases cortas con resaltado palabra a palabra sincronizado con el audio
// ==========================================
const subtitulos = (() => {
    const contenedor = document.getElementById('subtitles-container');
    const caja = document.getElementById('subtitles-text');
    const MAX_CARACTERES = 70; // longitud máxima de cada frase en pantalla
    let frases = [];
    let audio = null;
    let frameId = null;
    let fraseActual = -1;

    // Divide el texto en frases cortas, cortando preferentemente en signos de puntuación.
    // Cada palabra recibe un instante de inicio proporcional a su longitud, con pausas extra tras la puntuación.
    function preparar(texto) {
        const palabras = texto.replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
        const pesos = palabras.map(p => p.length + 1 + (/[.!?…:]$/.test(p) ? 6 : /[,;]$/.test(p) ? 3 : 0));
        const total = pesos.reduce((a, b) => a + b, 0) || 1;
        let acumulado = 0;
        const items = palabras.map((p, i) => {
            const item = { texto: p, inicio: acumulado / total };
            acumulado += pesos[i];
            return item;
        });
        frases = [];
        let actual = [];
        let largo = 0;
        items.forEach((item, i) => {
            actual.push(item);
            largo += item.texto.length + 1;
            const finDeOracion = /[.!?…:;,]$/.test(item.texto);
            if (largo >= MAX_CARACTERES || (finDeOracion && largo > 28) || i === items.length - 1) {
                frases.push({ palabras: actual, inicio: actual[0].inicio });
                actual = [];
                largo = 0;
            }
        });
    }

    function mostrarFrase(indice) {
        fraseActual = indice;
        caja.classList.remove('entrando');
        caja.innerHTML = '';
        frases[indice].palabras.forEach((p, i) => {
            const span = document.createElement('span');
            span.className = 'sub-palabra';
            span.textContent = p.texto;
            caja.appendChild(span);
            if (i < frases[indice].palabras.length - 1) caja.appendChild(document.createTextNode(' '));
        });
        void caja.offsetWidth; // reinicia la animación de entrada
        caja.classList.add('entrando');
    }

    function actualizar() {
        if (!audio) return;
        if (audio.duration && isFinite(audio.duration)) {
            const progreso = audio.currentTime / audio.duration;
            let indice = 0;
            while (indice + 1 < frases.length && frases[indice + 1].inicio <= progreso) indice++;
            if (indice !== fraseActual) mostrarFrase(indice);
            const spans = caja.querySelectorAll('.sub-palabra');
            frases[indice].palabras.forEach((p, i) => {
                const dicha = p.inicio <= progreso;
                const siguiente = frases[indice].palabras[i + 1];
                const actual = dicha && (!siguiente || siguiente.inicio > progreso);
                spans[i].classList.toggle('dicha', dicha);
                spans[i].classList.toggle('actual', actual);
            });
        }
        frameId = requestAnimationFrame(actualizar);
    }

    return {
        iniciar(texto, audioActual) {
            if (!contenedor || !caja) return;
            this.detener(false);
            preparar(texto.replace(/[*#_]/g, ''));
            if (!frases.length) return;
            audio = audioActual;
            mostrarFrase(0);
            if (subtitlesEnabled) contenedor.classList.remove('hidden');
            frameId = requestAnimationFrame(actualizar);
        },
        detener(ocultar = true) {
            if (frameId) cancelAnimationFrame(frameId);
            frameId = null;
            audio = null;
            fraseActual = -1;
            if (ocultar && contenedor) contenedor.classList.add('hidden');
        },
    };
})();

// 2.1 Text-to-Speech Sincronizado (El VRM Habla)
async function speakTextAndShow(text, yaMostrado = false) {
    let cleanText = text.replace(/[*#_]/g, '').trim();
    if (!cleanText) {
        if (currentMode === "chat") {
            removeLoading();
            if (!yaMostrado) addMessage(text, false);
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
        if (currentAudio.onended) currentAudio.onended(); // Limpia los subtítulos y UI
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
            setEstadoAvatar('reposo');
            if (currentMode === "chat") {
                removeLoading();
                if (!yaMostrado) addMessage(text, false);
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
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0.4;
        labios.preparar(cleanText);
        dataArray = new Uint8Array(analyser.frequencyBinCount);

        source.connect(analyser);
        analyser.connect(audioContext.destination);

        audio.onplay = () => {
            isSpeaking = true;
            setEstadoAvatar('hablando');
            if (currentMode === "conversational") {
                document.getElementById('convStatus').textContent = "Aria está hablando...";
                subtitulos.iniciar(text, audio);
            }
        };
        audio.onended = () => {
            isSpeaking = false;
            setEstadoAvatar('reposo');
            if (currentVrm) {
                currentVrm.expressionManager.setValue('aa', 0);
                currentVrm.expressionManager.setValue('happy', 0);
            }
            subtitulos.detener();

            if (currentMode === "conversational") {
                document.getElementById('convStatus').textContent = "Toca el micrófono para hablar con Aria";
                document.getElementById('convWaves').classList.remove('active');
            }
        };

        // ---> Sincronización <---
        if (currentMode === "chat") {
            removeLoading();
            if (!yaMostrado) addMessage(text, false);
        }
        await audio.play();

    } catch (err) {
        console.error("Error conectando con la voz neuronal:", err);
        setEstadoAvatar('reposo');
        if (currentMode === "chat") {
            removeLoading();
            if (!yaMostrado) addMessage(text, false);
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
            setEstadoAvatar('escuchando');
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
            setEstadoAvatar('pensando');
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
            setEstadoAvatar('reposo');
            if (currentMode === "chat") {
                userInput.placeholder = "No se detectó voz.";
            } else {
                document.getElementById('convStatus').textContent = "No se detectó voz.";
            }
        }
    } catch (error) {
        console.error("Error transcribiendo el audio:", error);
        setEstadoAvatar('reposo');
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
const toggleCameraBtn = document.getElementById('toggleCameraBtn');
let isUserCameraPreferenceOn = true; // Cámara activa por defecto en modo conversacional

if (toggleCameraBtn) {
    toggleCameraBtn.addEventListener('click', () => {
        if (currentMode !== 'conversational') return;
        isUserCameraPreferenceOn = !isUserCameraPreferenceOn;
        if (isUserCameraPreferenceOn) {
            toggleCameraBtn.classList.remove('inactive');
            toggleCameraBtn.classList.add('active');
            startCameraForVision();
        } else {
            toggleCameraBtn.classList.remove('active');
            toggleCameraBtn.classList.add('inactive');
            stopCameraForVision();
        }
    });
}

// Botón de subtítulos
const toggleSubtitlesBtn = document.getElementById('toggleSubtitlesBtn');
let subtitlesEnabled = true;

if (toggleSubtitlesBtn) {
    toggleSubtitlesBtn.addEventListener('click', () => {
        subtitlesEnabled = !subtitlesEnabled;
        // Toggle visual state on the HUD icon box
        if (subtitlesEnabled) {
            toggleSubtitlesBtn.classList.remove('inactive');
            toggleSubtitlesBtn.classList.add('active');
        } else {
            toggleSubtitlesBtn.classList.remove('active');
            toggleSubtitlesBtn.classList.add('inactive');
        }
        
        const subsOverlay = document.getElementById('subtitles-container');
        if (subsOverlay) {
            if (!subtitlesEnabled) {
                subsOverlay.classList.add('hidden');
            } else if (isSpeaking) {
                subsOverlay.classList.remove('hidden');
            }
        }
    });
}
modeChatBtn.addEventListener('click', () => {
    currentMode = "chat";
    modeChatBtn.classList.add('active');
    modeConvBtn.classList.remove('active');
    chatModeContainer.classList.add('active-mode');
    chatModeContainer.classList.remove('hidden-mode');
    convModeContainer.classList.remove('active-mode');
    convModeContainer.classList.add('hidden-mode');
    if (typeof stopCameraForVision === 'function') stopCameraForVision();
});

modeConvBtn.addEventListener('click', () => {
    currentMode = "conversational";
    modeConvBtn.classList.add('active');
    modeChatBtn.classList.remove('active');
    convModeContainer.classList.add('active-mode');
    convModeContainer.classList.remove('hidden-mode');
    chatModeContainer.classList.remove('active-mode');
    chatModeContainer.classList.add('hidden-mode');
    if (isUserCameraPreferenceOn && typeof startCameraForVision === 'function') {
        startCameraForVision();
    }
});

// ==========================================
// 3. WebSocket de presencia (eventos person_arrived / person_left)
// ==========================================
const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);

let hasWelcomed = false;
let wasInterrupted = false;

// ==========================================
// 4. Visión artificial en el cliente (MediaPipe Face Detector)
// La detección se ejecuta en el navegador; al servidor solo se envían las cajas delimitadoras.
// ==========================================
const MEDIAPIPE_URL = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14';
const INTERVALO_DETECCION_MS = 1000;

let videoElement = document.createElement('video');
videoElement.autoplay = true;
videoElement.muted = true;
videoElement.playsInline = true;
videoElement.style.display = 'none';
document.body.appendChild(videoElement);

let isCameraActive = false;
let visionInterval = null;
let visionStream = null;
let detectorRostros = null;

async function cargarDetectorRostros() {
    if (detectorRostros) return detectorRostros;
    const { FilesetResolver, FaceDetector } = await import(`${MEDIAPIPE_URL}/vision_bundle.mjs`);
    const fileset = await FilesetResolver.forVisionTasks(`${MEDIAPIPE_URL}/wasm`);
    detectorRostros = await FaceDetector.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: '/static/models/blaze_face_short_range.tflite', delegate: 'GPU' },
        runningMode: 'VIDEO',
        minDetectionConfidence: 0.5
    });
    return detectorRostros;
}

function detectarCajas() {
    const { detections } = detectorRostros.detectForVideo(videoElement, performance.now());
    return detections.map(({ boundingBox: c }) => [Math.round(c.originX), Math.round(c.originY), Math.round(c.width), Math.round(c.height)]);
}

let iniciandoCamara = false;

async function startCameraForVision() {
    if (isCameraActive || iniciandoCamara) return;
    iniciandoCamara = true;
    try {
        visionStream = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240 } });
        videoElement.srcObject = visionStream;
        await cargarDetectorRostros();
        if (!visionStream) return; // la cámara se apagó mientras cargaba el modelo
        
        const camBtn = document.getElementById('toggleCameraBtn');
        if (camBtn) {
            camBtn.classList.remove('inactive');
            camBtn.classList.add('active');
        }
        
        isCameraActive = true;
        visionInterval = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN && isCameraActive && videoElement.readyState >= 2) {
                ws.send(JSON.stringify({ cajas: detectarCajas() }));
            }
        }, INTERVALO_DETECCION_MS);
    } catch (err) {
        console.error("Error al iniciar la visión artificial:", err);
        stopCameraForVision();
    } finally {
        iniciandoCamara = false;
    }
}

function stopCameraForVision() {
    isCameraActive = false;
    
    if (visionInterval) {
        clearInterval(visionInterval);
        visionInterval = null;
    }
    
    if (visionStream) {
        visionStream.getTracks().forEach(track => track.stop());
        visionStream = null;
    }
    
    const camBtn = document.getElementById('toggleCameraBtn');
    if (camBtn) {
        camBtn.classList.remove('active');
        camBtn.classList.add('inactive');
    }
}

ws.onopen = () => {
    console.log("Conectado al canal de presencia (detección facial en el navegador)");
    if (currentMode === "conversational" && isUserCameraPreferenceOn) {
        startCameraForVision();
    }
};

ws.onmessage = (event) => {
    const action = event.data;
    const statusIndicator = document.getElementById('statusIndicator');

    if (action === "person_arrived") {
        lanzarGesto('saludo');
        if (statusIndicator) {
            statusIndicator.classList.remove('inactive');
            statusIndicator.classList.add('active');
            // Tooltip visual
            statusIndicator.setAttribute('title', 'Usuario detectado en cámara');
        }

        if (!hasWelcomed) {
            hasWelcomed = true;
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
        if (statusIndicator) {
            statusIndicator.classList.remove('active');
            statusIndicator.classList.add('inactive');
            statusIndicator.setAttribute('title', 'Usuario se alejó de la cámara');
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
    console.error('Error de conexión WebSocket de presencia');
};

// Función para las preguntas sugeridas en la interfaz
window.askSuggestion = function(btn) {
    const text = btn.innerText;
    const userInput = document.getElementById('userInput');
    userInput.value = text;
    
    // Forzar el modo chat para que la pregunta sea escrita y no genere confusión
    const modeChatBtn = document.getElementById('modeChatBtn');
    if (modeChatBtn && !modeChatBtn.classList.contains('active')) {
        modeChatBtn.click();
    }
    
    // Enviar el mensaje usando el botón de enviar
    const sendBtn = document.getElementById('sendBtn');
    if (sendBtn) sendBtn.click();
};

// ==========================================
// Carrusel infinito de preguntas sugeridas
// Se desplaza con transform (sin scrollLeft), admite flechas, arrastre y pausa al pasar el cursor.
// ==========================================
(function iniciarCarrusel() {
    const viewport = document.getElementById('suggestionViewport');
    const track = document.getElementById('suggestionTrack');
    if (!viewport || !track) return;

    const originales = Array.from(track.children);
    if (!originales.length) return;
    originales.forEach(b => {
        const copia = b.cloneNode(true);
        copia.setAttribute('aria-hidden', 'true');
        copia.tabIndex = -1;
        track.appendChild(copia);
    });

    const VELOCIDAD = 32; // px por segundo
    const movimientoReducido = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let anchoSerie = 0;      // ancho de una serie completa de preguntas (incluye el espacio entre ellas)
    let desplazamiento = 0;  // posición actual en px
    let objetivo = null;     // destino al usar las flechas
    let pausado = false;
    let arrastre = null;
    let ultimo = performance.now();

    const medir = () => {
        anchoSerie = track.children[originales.length].offsetLeft - originales[0].offsetLeft;
    };
    const paso = () => {
        const estilo = getComputedStyle(track);
        return originales[0].offsetWidth + (parseFloat(estilo.columnGap) || 12);
    };
    const normalizar = () => {
        if (anchoSerie <= 0) return;
        while (desplazamiento >= anchoSerie) { desplazamiento -= anchoSerie; if (objetivo !== null) objetivo -= anchoSerie; }
        while (desplazamiento < 0) { desplazamiento += anchoSerie; if (objetivo !== null) objetivo += anchoSerie; }
    };

    function cuadro(ahora) {
        const dt = Math.min((ahora - ultimo) / 1000, 0.1);
        ultimo = ahora;
        if (!arrastre) {
            if (objetivo !== null) {
                desplazamiento += (objetivo - desplazamiento) * Math.min(1, dt * 7);
                if (Math.abs(objetivo - desplazamiento) < 0.5) { desplazamiento = objetivo; objetivo = null; }
            } else if (!pausado && !movimientoReducido && !document.hidden) {
                desplazamiento += VELOCIDAD * dt;
            }
        }
        normalizar();
        track.style.transform = `translate3d(${-desplazamiento}px, 0, 0)`;
        requestAnimationFrame(cuadro);
    }

    // Flechas: avanzan o retroceden una pregunta con desplazamiento suave
    const mover = (direccion) => { objetivo = (objetivo ?? desplazamiento) + direccion * paso(); };
    document.getElementById('sugPrev')?.addEventListener('click', () => mover(-1));
    document.getElementById('sugNext')?.addEventListener('click', () => mover(1));

    // Pausa al pasar el ratón o al navegar con el teclado
    viewport.addEventListener('pointerenter', (e) => { if (e.pointerType === 'mouse') pausado = true; });
    viewport.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse') pausado = false; });
    viewport.addEventListener('focusin', () => { pausado = true; });
    viewport.addEventListener('focusout', () => { pausado = false; });

    // Arrastre con el dedo o el ratón; un arrastre no dispara la pregunta
    viewport.addEventListener('pointerdown', (e) => {
        arrastre = { x: e.clientX, inicio: desplazamiento, movido: false, id: e.pointerId };
        objetivo = null;
    });
    window.addEventListener('pointermove', (e) => {
        if (!arrastre || e.pointerId !== arrastre.id) return;
        const dx = e.clientX - arrastre.x;
        if (Math.abs(dx) > 6 && !arrastre.movido) {
            arrastre.movido = true;
            viewport.setPointerCapture(e.pointerId);
            viewport.classList.add('arrastrando');
        }
        if (arrastre.movido) desplazamiento = arrastre.inicio - dx;
    });
    const soltar = (e) => {
        if (!arrastre || e.pointerId !== arrastre.id) return;
        if (arrastre.movido) {
            const bloquearClic = (ev) => { ev.stopPropagation(); ev.preventDefault(); };
            viewport.addEventListener('click', bloquearClic, { capture: true, once: true });
            setTimeout(() => viewport.removeEventListener('click', bloquearClic, { capture: true }), 0);
        }
        viewport.classList.remove('arrastrando');
        arrastre = null;
    };
    window.addEventListener('pointerup', soltar);
    window.addEventListener('pointercancel', soltar);

    medir();
    new ResizeObserver(medir).observe(track);
    requestAnimationFrame(cuadro);
})();

// Verificar el rol del usuario actual para mostrar/ocultar el botón de Admin
fetch('/api/me')
    .then(res => res.json())
    .then(data => {
        if (data && data.is_admin) {
            const adminBtn = document.getElementById('adminBtn');
            if (adminBtn) adminBtn.style.display = 'inline-flex';
        }
    })
    .catch(err => console.error("Error verificando rol:", err));
