# Virus Spillover Simulator

Interactive web application for a spatial stochastic spillover model, implemented with Python 3.11, FastAPI/Uvicorn, a static HTML/CSS/JavaScript frontend, and Docker.

## Example interpretation

The interface presents a **toy example inspired by Nipah virus spillover in Bangladesh**:

- `K_r(x)`: spatial reservoir density of *Pteropus medius* bats;
- `P(x, theta)`: Nipah pathogen density;
- `K_s(x)`: human population density, interpreted as the spillover-host density;
- `alpha(x)`: a spatial covariate corresponding to date-palm consumption.

This example is illustrative rather than epidemiologically calibrated. Several parameters are demo values and should be adjusted against appropriate epidemiological and ecological data before the numerical outputs are interpreted as realistic.

## Model

Pathogen density is

`P(x, theta) = G(theta) [J_D * K_r](x)`,

where `G` is the standard Gaussian density and `J_D` is a two-dimensional Gaussian spatial kernel with covariance `D I`. In the implementation, `D` is expressed in `km^2`, so the spatial standard deviation is `sqrt(D)` km.

Primary spillover infections in the human population arise from a marked Poisson process with intensity density

`(beta0 + beta1 alpha(x)) K_s(x) P(x, theta)`.

Because `G(theta)` integrates to one, the spatial intensity used to sample spillover locations is

`(beta0 + beta1 alpha(x)) K_s(x) [J_D * K_r](x)`.

Each primary infection receives an independent pathogen trait `theta ~ N(0,1)` and initiates a continuous-time linear birth-death transmission process simulated with a Gillespie algorithm:

- `b(theta) = b0`
- `d(theta) = d0 + (theta - O_s)^2`

Here, the birth rate represents onward transmission and the death/removal rate represents termination of infectious lineages. These parameters therefore control the length and persistence of local transmission chains. A chain is locally supercritical when

`b0 > d0 + (theta - O_s)^2`.

## Default parameters

The current interactive defaults are:

- `D = 500 km^2`
- `beta0 = 5e-8`
- `beta1 = 2e-8`
- `b0 = 0.5`
- `d0 = 0.3`
- `O_s = 0`
- duration `= 50` model-time units
- random seed `= 2030`

`D`, `beta0`, `beta1`, `b0`, `d0`, and `O_s` are editable in the interface.

The backend also imposes safety limits on the number and size of simulated transmission chains so that parameter combinations that are too large for an interactive browser animation return a readable error rather than an unusable response.

## Run locally with Docker Desktop

From the project directory:

```bash
docker compose up --build
```

Then open:

```text
http://localhost:8000
```

Health check:

```text
http://localhost:8000/health
```

Stop the application with:

```bash
docker compose down
```

You can also use plain Docker:

```bash
docker build -t virus-spillover-sim .
docker run --rm -p 127.0.0.1:8000:8000 virus-spillover-sim
```

## Run without Docker

Python 3.11 is recommended.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

If Node.js is installed, the frontend syntax can also be checked with:

```bash
node --check app/static/app.js
```

## Deployment on a VM

The app is suitable for the same deployment pattern as a small FastAPI application behind a reverse proxy:

1. copy or clone the project on the VM;
2. run `docker compose up -d --build`;
3. expose only the reverse proxy publicly and proxy the hostname to `127.0.0.1:8000`;
4. use `/health` for the health check;
5. terminate HTTPS at the reverse proxy, for example with Nginx, Caddy, or Traefik.

No application state is stored on disk, so container replacement and restart are straightforward.

## Project layout

```text
virus-spillover-sim/
├── app/
│   ├── main.py
│   ├── model.py
│   ├── render.py
│   ├── data/
│   │   └── spatial_maps.npz
│   └── static/
│       ├── index.html
│       ├── style.css
│       └── app.js
├── tests/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── requirements-dev.txt
```

## Credits shown in the web app

- Data (`K_r`): to be added
- Data (`K_s`): www.worldpop.org
- Data (`alpha`): to be added
- Model: O. Bonnefon, C. Chane-Ki-Chune, G. Fournié, L. Roques
- Web-app: L. Houde, S. Lanoë, L. Roques
