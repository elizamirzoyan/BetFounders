import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

USER_STATE = {1: "Active", 2: "Deactivated", 3: "Pending activation"}
CODE_STATE = {1: "Succeed", 2: "Expired", 0: "Pending activation", 3: "Pending activation"}
COLORS = {"Active": "#2e7d32", "Succeed": "#2e7d32", "Expired": "#c62828",
          "Pending activation": "#f9a825", "Deactivated": "#757575"}
MAX_EXPIRED = 5
PLOTLY_JS = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@3.5.0/plotly.min.js"

raw_users = pd.read_csv("User.csv")
users = raw_users.drop_duplicates().copy()
users["RegistrationDate"] = pd.to_datetime(users["RegistrationDate"])
users["StateName"] = users["State"].map(USER_STATE)


def load_codes(path):
    df = pd.read_csv(path).dropna()
    df = df.astype({"UserID": int, "State": int})
    df["CreationDate"] = pd.to_datetime(df["CreationDate"])
    df["StateName"] = df["State"].map(CODE_STATE)
    return df


register = load_codes("RegisterCode.csv")
reset = load_codes("RegsetCode.csv")


def registrations_chart():
    daily = (users.groupby([users["RegistrationDate"].dt.date, "StateName"])
             .size().unstack(fill_value=0))
    fig = go.Figure([go.Bar(x=daily.index, y=daily[s], name=s, marker_color=COLORS[s])
                     for s in daily.columns])
    fig.update_layout(barmode="stack", title=f"Daily registrations ({len(users)} users)",
                      xaxis_title="Date", yaxis_title="Registrations",
                      legend_title="User state", hovermode="x unified")
    print("Registrations by user state:")
    print(users["StateName"].value_counts().to_string(), "\n")
    return fig


def success_rate(codes, name):
    counts = codes["StateName"].value_counts()
    code_rate = (codes["State"] == 1).mean() * 100
    user_rate = codes.groupby("UserID")["State"].apply(lambda s: (s == 1).any()).mean() * 100
    daily = codes.groupby(codes["CreationDate"].dt.date)["State"].agg(
        rate=lambda s: (s == 1).mean() * 100, total="size")

    fig = make_subplots(rows=1, cols=2, column_widths=[0.35, 0.65],
                        specs=[[{"type": "domain"}, {"type": "xy"}]],
                        subplot_titles=[f"{name} code states ({len(codes)} codes)",
                                        f"Daily {name.lower()} code success rate"])
    fig.add_trace(go.Pie(labels=counts.index, values=counts.values, hole=0.4,
                         marker_colors=[COLORS[s] for s in counts.index]), 1, 1)
    fig.add_trace(go.Scatter(x=daily.index, y=daily["rate"], mode="lines+markers",
                             name="Daily rate", customdata=daily["total"],
                             hovertemplate="%{x}<br>%{y:.1f}% of %{customdata} codes<extra></extra>"),
                  1, 2)
    fig.add_trace(go.Scatter(x=[daily.index.min(), daily.index.max()], y=[code_rate] * 2,
                             mode="lines", name=f"Overall {code_rate:.1f}%",
                             line=dict(dash="dash", color="gray")), 1, 2)
    fig.update_yaxes(title="Success rate (%)", range=[0, 105], row=1, col=2)
    fig.update_xaxes(title="Date", row=1, col=2)

    print(f"{name} code success rate:")
    print(counts.to_string())
    print(f"Per code: {code_rate:.1f}%  |  Per user (at least one success): {user_rate:.1f}%\n")
    return fig, code_rate, user_rate


def problematic_users():
    reg = register[register["UserID"].isin(users["ID"])]
    stats = reg.groupby("UserID")["State"].agg(
        succeeded=lambda s: (s == 1).sum(),
        expired=lambda s: (s == 2).sum(),
        pending=lambda s: (s == 0).sum(),
    )
    df = users.set_index("ID").join(stats)
    df[stats.columns] = df[stats.columns].fillna(0).astype(int)
    reset_ok = reset[reset["State"] == 1]["UserID"]

    rules = {
        "No register code": ~df.index.isin(reg["UserID"]),
        "Active without succeeded register code": (df["State"] == 1) & (df["succeeded"] == 0),
        "Pending user with succeeded register code": (df["State"] == 3) & (df["succeeded"] > 0),
        "More than one succeeded register code": df["succeeded"] > 1,
        f"{MAX_EXPIRED}+ expired register codes": df["expired"] >= MAX_EXPIRED,
        "Pending user with succeeded reset code": (df["State"] == 3) & df.index.isin(reset_ok),
    }
    issues = pd.DataFrame(rules, index=df.index)
    df["Issues"] = issues.apply(lambda r: "; ".join(r.index[r]), axis=1)
    result = df[issues.any(axis=1)].reset_index()[
        ["ID", "StateName", "RegistrationDate", "succeeded", "expired", "pending", "Issues"]]
    result = result.rename(columns={"ID": "UserID", "StateName": "UserState"})
    os.makedirs("public", exist_ok=True)
    result.to_csv("public/problematic_users.csv", index=False)

    counts = issues.sum()
    fig = go.Figure(go.Bar(x=counts.values, y=counts.index, orientation="h",
                           marker_color="#c62828", text=counts.values))
    fig.update_layout(title=f"Problematic users by issue ({len(result)} users)",
                      xaxis_title="Users", yaxis_autorange="reversed")

    print(f"Problematic users: {len(result)}")
    print(counts.to_string())
    print(f"User.csv had {len(raw_users) - len(users)} duplicate rows (removed)")
    return fig, result


def build_report(figs, reset_rates, register_rates, problems):
    charts = "".join(
        f"<section><h2>{title}</h2>{fig.to_html(full_html=False, include_plotlyjs=False)}</section>"
        for title, fig in figs)
    table = problems.assign(RegistrationDate=problems["RegistrationDate"].dt.strftime("%Y-%m-%d %H:%M")) \
        .to_html(index=False, border=0)
    cards = [("Users", f"{len(users):,}"),
             ("Reset code success", f"{reset_rates[0]:.1f}%"),
             ("Register code success", f"{register_rates[0]:.1f}%"),
             ("Problematic users", f"{len(problems)}")]
    cards_html = "".join(f"<div class='card'><span>{k}</span><b>{v}</b></div>" for k, v in cards)
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BetFounders Data Report</title>
<script src="{PLOTLY_JS}"></script>
<style>
body {{ font-family: system-ui, sans-serif; margin: 0 auto; max-width: 1200px; padding: 24px 16px; color: #222; background: #fafafa; }}
section {{ background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 24px; box-shadow: 0 1px 3px #0001; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
.card {{ background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px #0001; }}
.card span {{ display: block; color: #666; font-size: 14px; }} .card b {{ font-size: 28px; }}
.download {{ display: inline-block; background: #2e7d32; color: #fff; padding: 8px 14px; border-radius: 6px; text-decoration: none; }}
.table {{ max-height: 500px; overflow: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ padding: 6px 10px; border-bottom: 1px solid #eee; text-align: left; }}
th {{ position: sticky; top: 0; background: #f0f0f0; }}
</style></head><body>
<h1>BetFounders Data Report</h1>
<div class="cards">{cards_html}</div>
{charts}
<section><h2>Problematic user list</h2>
<p><a class="download" href="problematic_users.csv" download>Download CSV ({len(problems)} users)</a></p>
<div class="table">{table}</div></section>
</body></html>"""
    with open("public/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("\nSaved public/index.html")


reg_fig = registrations_chart()
reset_fig, *reset_rates = success_rate(reset, "Reset")
register_fig, *register_rates = success_rate(register, "Register")
problem_fig, problems = problematic_users()
build_report([("1. Registrations", reg_fig),
              ("2. Reset code success rate", reset_fig),
              ("3. Register code success rate", register_fig),
              ("4. Problematic users", problem_fig)],
             reset_rates, register_rates, problems)
