# Roadmap - planejado, ainda não implementado

Esta página existe para ser honesta sobre o que o FAROL **ainda não faz**, em vez de deixar essas
lacunas implícitas ou espalhadas em páginas que parecem descrever algo funcional. Nada abaixo tem
código - são decisões de arquitetura já tomadas, aguardando implementação.

O plugin preventivo (`ckanext-farol-guard`) **já está construído** - ver
[Plugin preventivo](plugin-ckan.md), não esta página.

## Notificação plugável

Arquitetura pretendida: uma interface única `Notificador`, com backends plugáveis (e-mail/SMTP,
bot do Telegram, ticket via API REST do OTRS, webhook genérico para Slack/Teams/GLPI), canal e
limiar de severidade escolhidos por configuração, não por código. **Não implementado** - hoje a
única forma de saber que um achado novo apareceu é abrir o painel técnico.

## Scan agendado

O `scanner` roda hoje só sob demanda, disparado pela tela `/scan` do painel técnico (ver
[Rodar o scanner](rodar-o-scanner.md)) - não há um scheduler embutido no FAROL, nem integração
com agendador externo (`cron`, `systemd timer`). O **modo incremental** (também já construído,
ver a mesma página) cobre boa parte da necessidade prática - reavaliar só dataset novo ou
alterado, sem custo de reprocessar tudo - mas ainda depende de alguém disparar o scan de novo
manualmente; disparo automático em horário fixo continua não implementado.

O painel gerencial (risco agregado por órgão, tendência no tempo, % de cobertura, voltado a
quem decide) **já está construído** - ver
[Painel gerencial](../guia-do-usuario/painel-gerencial.md), não esta página.
