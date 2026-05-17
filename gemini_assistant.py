import os
import sys
import time
import google.generativeai as genai
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configurar API de Gemini
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY or API_KEY == "TU_API_KEY_AQUI":
    print("❌ Por favor, configura tu GEMINI_API_KEY en el archivo .env")
    sys.exit(1)

genai.configure(api_key=API_KEY)

def upload_to_gemini(path, mime_type=None):
    """Sube el archivo proporcionado a la API de archivos de Gemini."""
    try:
        print(f"Subiendo {path} a Gemini...")
        file = genai.upload_file(path, mime_type=mime_type)
        print(f"✅ Archivo subido exitosamente URI: {file.uri}")
        return file
    except Exception as e:
        print(f"❌ Error al subir el archivo: {e}")
        sys.exit(1)

def wait_for_files_active(files):
    """Espera a que los archivos estén listos para procesarse."""
    print("Procesando documento...")
    for name in (file.name for file in files):
        file = genai.get_file(name)
        while file.state.name == "PROCESSING":
            print(".", end="", flush=True)
            time.sleep(2)
            file = genai.get_file(name)
        if file.state.name != "ACTIVE":
            raise Exception(f"El archivo {file.name} no se procesó correctamente.")
    print()
    print("✅ Documento listo para usar.")

def main():
    pdf_path = "carrera_iti.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"❌ No se encontró el archivo: {pdf_path}")
        sys.exit(1)

    # 1. Subir documento
    pdf_file = upload_to_gemini(pdf_path, mime_type="application/pdf")
    wait_for_files_active([pdf_file])

    # 2. Configurar el System Prompt (Instrucción inicial)
    system_instruction = (
        "Eres un asistente virtual universitario amigable y experto."
        "Tu objetivo es ayudar a los estudiantes resolviendo dudas específicas sobre su carrera "
        "basándote ÚNICA Y EXCLUSIVAMENTE en el documento PDF proporcionado. "
        "Responde de forma concisa, clara y con un tono entusiasta. "
        "Si alguien te saluda, preséntate como el Asistente Virtual de la Carrera. "
        "Si te preguntan algo que no esté en el documento, indica amablemente que no tienes esa información."
    )

    # Configuramos el modelo Gemini (rapidez y soporte de documentos)
    model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_instruction
    )

    # 3. Crear sesión de chat con el documento como contexto inicial
    print("\nIniciando Chatbot...")
    chat_session = model.start_chat(
        history=[
            {
                "role": "user",
                "parts": [
                    pdf_file,
                    "Revisa este documento sobre mi carrera universitaria, te haré preguntas al respecto."
                ],
            },
            {
               "role": "model",
               "parts": ["¡Entendido! He revisado el documento sobre la carrera universitaria. ¡Pregúntame lo que necesites!"]
            }
        ]
    )

    print("\n" + "="*50)
    print("🤖 ASISTENTE VIRTUAL INICIADO (Escribe 'salir' para terminar)")
    print("="*50)
    
    # 4. Iniciar bucle de chat en consola
    while True:
        try:
            user_input = input("\n👤 Tú: ")
            if user_input.lower() in ['salir', 'exit', 'quit']:
                print("🤖 Asistente: ¡Hasta luego! Mucho éxito en tu carrera.")
                break
                
            if not user_input.strip():
                continue

            # Mostrar que está procesando
            print("🤖 Asistente: Pensando...", end="\r")
            
            response = chat_session.send_message(user_input)
            
            # Limpiar la línea de "Pensando..." y mostrar la respuesta real
            print(" " * 30, end="\r")
            print(f"🤖 Asistente: {response.text}")
            
        except KeyboardInterrupt:
            print("\n🤖 Asistente: ¡Hasta luego! Mucho éxito en tu carrera.")
            break
        except Exception as e:
            print(f"\n❌ Ocurrió un error: {e}")

if __name__ == "__main__":
    main()
