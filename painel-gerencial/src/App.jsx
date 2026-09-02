import React, { useEffect, useState } from 'react';
import GraficoTendencia from './GraficoTendencia.jsx';

function useTema() {
  useEffect(() => {
    const armazenado = localStorage.getItem('farol-theme');
    if (armazenado) document.documentElement.setAttribute('data-theme', armazenado);
  }, []);

  const alternar = () => {
    const raiz = document.documentElement;
    const atual = raiz.getAttribute('data-theme')
      || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const proximo = atual === 'dark' ? 'light' : 'dark';
    raiz.setAttribute('data-theme', proximo);
    localStorage.setItem('farol-theme', proximo);
  };

  return alternar;
}

// Toda chamada de API roda por aqui: cookie de sessao vai automaticamente
// (fetch same-origin ja inclui por padrao), 401 significa sessao expirada
// ou nunca logada. Quem trata o redirect pra tela de login PROPRIA do
// gerencial (mesmo backend do painel tecnico, sessao/credencial diferentes
// desde 2026-08-22 - ver _exigir_login_gerencial em painel/main.py) e' o
// componente App, para poder avisar o usuario antes de navegar embora.
async function buscar(caminho) {
  const resp = await fetch(caminho, { headers: { Accept: 'application/json' } });
  if (resp.status === 401) {
    const erroSessao = new Error('sessao expirada');
    erroSessao.sessaoExpirada = true;
    throw erroSessao;
  }
  if (!resp.ok) throw new Error(`erro ${resp.status} em ${caminho}`);
  return resp.json();
}

const URL_LOGIN_GERENCIAL = '/login-gerencial?proximo=/gerencial&motivo=sessao-expirada';
const ATRASO_REDIRECT_SESSAO_MS = 1200;

export default function App() {
  const alternarTema = useTema();
  const [ambiente, setAmbiente] = useState('producao');
  const [resumo, setResumo] = useState(null);
  const [orgaos, setOrgaos] = useState(null);
  const [tendencia, setTendencia] = useState(null);
  const [erro, setErro] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [sessaoExpirada, setSessaoExpirada] = useState(false);

  useEffect(() => {
    setErro(null);
    setCarregando(true);
    Promise.all([
      buscar(`/api/gerencial/resumo?ambiente=${ambiente}`),
      buscar(`/api/gerencial/por-orgao?ambiente=${ambiente}`),
      buscar(`/api/gerencial/tendencia?ambiente=${ambiente}&dias=30`),
    ])
      .then(([r, o, t]) => {
        setResumo(r);
        setOrgaos(o.orgaos);
        setTendencia(t.dias);
      })
      .catch((e) => {
        if (e.sessaoExpirada) {
          setSessaoExpirada(true);
          setTimeout(() => {
            window.location.href = URL_LOGIN_GERENCIAL;
          }, ATRASO_REDIRECT_SESSAO_MS);
          return;
        }
        setErro(e.message);
      })
      .finally(() => setCarregando(false));
  }, [ambiente]);

  return (
    <>
      <div className="topbar">
        <h1><img className="logo" src={`${import.meta.env.BASE_URL}farol-logo.svg`} alt="FAROL" width="32" height="32" /> FAROL - Painel gerencial</h1>
        <div className="topbar-actions">
          <div className="ambiente-tabs">
            <button className={ambiente === 'producao' ? 'ativo' : ''} onClick={() => setAmbiente('producao')}>
              Producao
            </button>
            <button className={ambiente === 'sintetico' ? 'ativo' : ''} onClick={() => setAmbiente('sintetico')}>
              Sintetico
            </button>
          </div>
          <a href="/">Painel tecnico</a>
          <button id="theme-toggle" type="button" onClick={alternarTema}>Alternar tema</button>
          <a href="/logout">Sair</a>
        </div>
      </div>

      {sessaoExpirada && (
        <p className="erro-carregamento">Sessao expirada. Redirecionando para o login...</p>
      )}
      {erro && !sessaoExpirada && <p className="erro-carregamento">Nao foi possivel carregar os dados agora: {erro}</p>}
      {carregando && !erro && !sessaoExpirada && (
        <p className="carregando"><span className="spinner" aria-hidden="true"></span> Carregando dados...</p>
      )}

      {resumo && (
        <section>
          <h2>Visao geral</h2>
          <div className="cards">
            <div className="card">
              <div className="label">Taxa de liberacao (achados)</div>
              <div className={`value ${resumo.score_conformidade !== null && resumo.score_conformidade < 70 ? 'crit' : ''}`}>
                {resumo.score_conformidade !== null ? `${resumo.score_conformidade}%` : '-'}
              </div>
              <div className="sub">liberados / achados avaliados - indicador operacional, nao e auditoria de conformidade LGPD</div>
            </div>
            <div className="card">
              <div className="label">Cobertura do catalogo</div>
              <div className="value">{resumo.cobertura !== null ? `${resumo.cobertura}%` : '-'}</div>
              <div className="sub">avaliados / total (o resto e' nao_analisado)</div>
            </div>
            <div className="card">
              <div className="label">Recursos auditados</div>
              <div className="value">{resumo.recursos_auditados}</div>
            </div>
            <div className="card">
              <div className="label">Pendentes de revisao</div>
              <div className={`value ${resumo.pendentes_revisao > 0 ? 'warn' : ''}`}>{resumo.pendentes_revisao}</div>
            </div>
            <div className="card">
              <div className="label">Confirmados como positivo</div>
              <div className={`value ${resumo.confirmados > 0 ? 'crit' : ''}`}>{resumo.confirmados}</div>
            </div>
          </div>
        </section>
      )}

      {tendencia && (
        <section>
          <h2>Achados por dia (ultimos 30 dias)</h2>
          <div className="painel">
            <GraficoTendencia dias={tendencia} />
          </div>
        </section>
      )}

      {orgaos && (
        <section>
          <h2>Ranking por orgao</h2>
          <div className="painel">
            {orgaos.length === 0 ? (
              <p className="vazio">Nenhum achado registrado neste ambiente ainda.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Orgao</th>
                    <th>Recursos auditados</th>
                    <th>Achados de alto risco</th>
                    <th>Pendentes de revisao</th>
                    <th>Nao analisados</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {orgaos.map((o) => {
                    const maximo = Math.max(1, ...orgaos.map((x) => x.achados_alto_risco));
                    return (
                      <tr key={o.org}>
                        <td>{o.org}</td>
                        <td>{o.recursos_auditados}</td>
                        <td>{o.achados_alto_risco}</td>
                        <td>{o.pendentes_revisao}</td>
                        <td>{o.nao_analisados}</td>
                        <td>
                          <div className="barra-org">
                            <div className="barra-org-preenchida"
                                 style={{ width: `${(o.achados_alto_risco / maximo) * 100}%` }} />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </section>
      )}
    </>
  );
}
