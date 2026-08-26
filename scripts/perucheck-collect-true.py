import requests
from bs4 import BeautifulSoup
import json
import time
import argparse
from pathlib import Path
from urllib.parse import urlparse, urlunparse
import threading
import concurrent.futures


def normalize_perucheck_url(url):
    """Normaliza URLs de PeruCheck para evitar 404 por rutas antiguas."""
    parsed = urlparse(url)
    path = parsed.path

    # Algunas fuentes vienen con /verificadas/... y el sitio actual usa /articles/verificadas/...
    if path.startswith('/verificadas/'):
        path = '/articles' + path

    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment))


def candidate_urls(url):
    """Devuelve variantes de URL para tolerar rutas antiguas/nuevas."""
    normalized = normalize_perucheck_url(url)
    candidates = [normalized]
    if normalized != url:
        candidates.append(url)
    return candidates


def detect_verdict_from_text(text):
    """Mapea texto del titular/contenido a una etiqueta de veredicto."""
    text = (text or '').lower()

    # Prioriza señales de verdadero, porque muchas notas usan "es cierto" y no "verdadero".
    if 'es cierto' in text or 'sí es cierto' in text or 'si es cierto' in text:
        return 'true'

    if 'no es cierto' in text or 'es falso' in text or 'falso' in text:
        return 'false'

    if 'impreciso' in text:
        return 'misleading'

    if 'engañoso' in text or 'enganoso' in text or 'parcialmente' in text:
        return 'misleading'

    return None

def extract_perucheck_data(url):
    """Extrae claim y veredicto de una URL de PeruCheck"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    last_error = None
    for candidate in candidate_urls(url):
        try:
            response = requests.get(candidate, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Busca el claim (generalmente en h1 o primera seccion)
            claim = None
            h1 = soup.find('h1')
            if h1:
                claim = h1.get_text(strip=True)

            # Detecta veredicto priorizando el titular, que en PeruCheck suele incluir "Es cierto/falso/impreciso".
            verdict = detect_verdict_from_text(claim)
            if verdict is None:
                verdict = detect_verdict_from_text(soup.get_text(' ', strip=True))

            return claim, verdict, candidate
        except Exception as e:
            last_error = e

    print(f"Error en {url}: {last_error}")
    return None, None, normalize_perucheck_url(url)

def process_perucheck_urls(urls_file, output_file, limit=None, delay=0.5):
    """Lee URLs y genera dataset de PeruCheck"""
    
    # Lee las URLs que ya tienes
    with open(urls_file, 'r') as f:
        urls = [line.strip() for line in f if line.strip()]

    if limit is not None:
        urls = urls[:limit]
    
    manager = {
        'count': 0,
        'lock': threading.Lock(),
        'stop_event': threading.Event()
    }

    # Preparar archivo de salida (lo reescribimos si no existe)
    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Inicializar set de URLs ya procesadas si queremos reanudar
    processed_urls = set()
    if out_path.exists():
        try:
            with open(out_path, 'r', encoding='utf-8') as f_out:
                for line in f_out:
                    try:
                        obj = json.loads(line)
                        if 'url' in obj:
                            processed_urls.add(obj['url'])
                    except Exception:
                        continue
        except Exception:
            processed_urls = set()

    # Worker para procesar una URL (retorna item o None)
    def worker(idx_url):
        i, url = idx_url
        if manager['stop_event'].is_set():
            return None
        print(f"[{i+1}/{len(urls)}] Procesando: {url}")
        claim, verdict, resolved_url = extract_perucheck_data(url)
        if claim and verdict == 'true':
            item = {
                'id': {i},
                'claim_text': claim,
                'label': 'true',
                'verdict_raw': 'Es cierto',
                'url': resolved_url,
                'source': 'perucheck',
                'date': None
            }
            return item
        else:
            print(f"  ✗ Skipped (verdict={verdict})")
            return None

    return None


def process_perucheck_urls_concurrent(urls_file, output_file, limit=None, delay=0.5, workers=5, target=None, resume=False):
    with open(urls_file, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip()]
    if limit is not None:
        urls = urls[:limit]

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing outputs if resume
    collected = 0
    processed_urls = set()
    if resume and out_path.exists():
        with open(out_path, 'r', encoding='utf-8') as f_out:
            for line in f_out:
                try:
                    obj = json.loads(line)
                    processed_urls.add(obj.get('url'))
                    collected += 1
                except Exception:
                    continue

    lock = threading.Lock()
    stop_event = threading.Event()

    def task(url_and_idx):
        i, url = url_and_idx
        if stop_event.is_set():
            return None
        if url in processed_urls:
            return None
        time.sleep(delay)  # pacing per task
        claim, verdict, resolved_url = extract_perucheck_data(url)
        if claim and verdict == 'true':
            item = {
                'id': f'perucheck_{i}',
                'claim_text': claim,
                'label': 'true',
                'verdict_raw': 'Es cierto',
                'url': resolved_url,
                'source': 'perucheck',
                'date': None
            }
            with lock:
                with open(out_path, 'a', encoding='utf-8') as f_out:
                    f_out.write(json.dumps(item, ensure_ascii=False) + '\n')
                nonlocal_collected[0] += 1
                print(f"  ✓ Guardado: {claim[:60]}...")
                if target and nonlocal_collected[0] >= target:
                    stop_event.set()
            return item
        else:
            print(f"  ✗ Skipped (verdict={verdict})")
            return None

    # Use a mutable integer for collected inside nested function
    nonlocal_collected = [collected]

    # Truncate output if not resume
    if not resume:
        open(out_path, 'w', encoding='utf-8').close()

    url_enumerated = list(enumerate(urls))

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(task, ui): ui for ui in url_enumerated}
        try:
            for fut in concurrent.futures.as_completed(futures):
                if stop_event.is_set():
                    break
                # iterate to let exceptions surface
                try:
                    _ = fut.result()
                except Exception as e:
                    print('Worker error:', e)
                    continue
        except KeyboardInterrupt:
            stop_event.set()
            executor.shutdown(wait=False, cancel_futures=True)

    print(f"\nTotal de noticias verdaderas extraídas: {nonlocal_collected[0]}")

def main():
    parser = argparse.ArgumentParser(description='Recolecta solo verificaciones verdaderas de PeruCheck.')
    parser.add_argument('--input', default='data/perucheck/urls.txt', help='Archivo con URLs, una por línea.')
    parser.add_argument('--output', default='data/perucheck/verdaderas.jsonl', help='Archivo de salida JSONL.')
    parser.add_argument('--limit', type=int, default=None, help='Procesa solo las primeras N URLs.')
    parser.add_argument('--delay', type=float, default=0.5, help='Pausa en segundos entre requests.')
    parser.add_argument('--workers', type=int, default=1, help='Número de workers concurrentes (1 = secuencial).')
    parser.add_argument('--target', type=int, default=None, help='Objetivo mínimo de items verdaderos a recolectar.')
    parser.add_argument('--resume', action='store_true', help='Si se especifica, reanuda desde archivo de salida existente y lo complementa.')
    args = parser.parse_args()

    process_perucheck_urls_concurrent(args.input, args.output, limit=args.limit, delay=args.delay, workers=args.workers, target=args.target, resume=args.resume)


if __name__ == '__main__':
    main()