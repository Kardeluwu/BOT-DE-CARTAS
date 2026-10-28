# Mi Card Pulse

Revisa tiendas TCG de Chile cada 10 minutos, agrupa los sellados de Pokémon y One Piece
bajo una sola ficha (set + tipo + idioma) y te avisa por Discord. Corre gratis en GitHub,
sin dejar tu PC prendido y sin gastar uso de Claude.

## Puesta en marcha (una sola vez, ~10 min)

1. **Webhook de Discord**: en tu servidor, Ajustes del canal → Integraciones → Webhooks →
   Nuevo webhook → Copiar URL.
2. **Repositorio**: crea una cuenta en github.com si no tienes, y un repositorio nuevo
   **público** (los públicos tienen Actions ilimitado; los precios ya son públicos igual).
   Sube todos estos archivos (botón "Add file → Upload files", incluida la carpeta `.github`).
3. **Secreto**: en el repo, Settings → Secrets and variables → Actions → New repository secret.
   Nombre: `DISCORD_WEBHOOK`, valor: la URL del paso 1. Así nadie más la ve.
4. **Página**: Settings → Pages → Branch `main`, carpeta `/docs` → Save.
   Tu comparador queda en `https://TU-USUARIO.github.io/NOMBRE-REPO/`.
5. **Cargar las tiendas**: pestaña Actions → "Descubrir tiendas" → Run workflow (unos 5 min).
   Lee los nombres de `tiendas.txt`, busca el sitio real de cada una y las agrega a `config.json`.
   Las que no encuentre quedan en `data/tiendas_no_encontradas.txt` para agregarlas a mano.
   Vuelve a correrlo cuando agregues nombres a `tiendas.txt`.
6. **Primera corrida**: pestaña Actions → "Mi Card Pulse" → Run workflow.
   La primera vez solo guarda lo que encuentra (no avisa, para no llenarte el canal).
   Desde ahí corre sola cada 10 minutos.

## Qué ajustar en `config.json`

| Campo | Para qué |
|---|---|
| `stores` | Tus tiendas: nombre y URL. Detecta sola si es Shopify, WooCommerce u otra. |
| `watch` | Palabras clave. Si un producto calza, avisa con ⭐ y te etiqueta, aunque no tenga stock. Ej: `"eb05"`, `"delta reign etb"`. |
| `only_watch` | `true` = solo avisa por tus palabras clave. `false` = avisa todo. |
| `watch_ping` | A quién etiquetar: `"@here"`, `"@everyone"`, `"<@TU_ID>"` o `""` para nadie. |
| `alert_types` | Qué avisos quieres: `nuevo`, `tienda` (otra tienda lo tiene), `repuesto`, `baja`. |
| `min_drop_pct` | Cuánto tiene que bajar un precio (%) para avisar. |
| `parallel` | Cuántas tiendas revisa a la vez (8 por defecto). |
| `big_store_products` / `big_store_every_min` | Tiendas con más de 3.000 productos (casi siempre singles) se revisan cada 60 min en vez de cada 10. |
| `aliases` | Reemplazos para nombres raros, ej. `["coleccion figura", "figure collection"]`. |

## Cuando algo no se agrupa bien

- Revisa `data/sin_set.txt`: lista los productos cuyo set no se reconoció.
- Agrega el set o el alias en `sets.json` (por ejemplo cuando salga un set nuevo).
- Los códigos de One Piece (OP17, OP-17, EB05, PRB01) se reconocen solos.

## Frecuencia

GitHub permite como mínimo cada 5 minutos (cambia `*/10` por `*/5` en
`.github/workflows/pulse.yml`), pero a veces atrasa las corridas unos minutos.
Si quieres avisos casi al instante, puedes correr `python pulse.py` en un PC o
Raspberry Pi siempre prendido con una tarea programada cada 1-2 minutos
(definiendo la variable de entorno `DISCORD_WEBHOOK`).

## Notas

- Shopify y WooCommerce se leen por su catálogo público (rápido, pocas visitas).
- Otras plataformas (ej. Jumpseller) se leen por el sitemap, abriendo solo páginas nuevas
  o cambiadas; puede tardar un par de corridas en tener el catálogo completo.
- Si una tienda falla, se mantienen sus datos anteriores y la página lo muestra arriba.
