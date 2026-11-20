# Publishing to PyPI / 发布到 PyPI

The package is published as
[`code-art-studio`](https://pypi.org/project/code-art-studio/); it is imported
as `codeart`. (`codeart` on PyPI belongs to an unrelated 2020 project.)

本包在 PyPI 上的名字是 `code-art-studio`，导入名是 `codeart`。PyPI 上的
`codeart` 已被一个 2020 年的无关项目占用。

## One-time setup / 首次设置

The `Publish to PyPI` workflow uploads with
[trusted publishing](https://docs.pypi.org/trusted-publishers/): PyPI accepts
uploads from this repository's workflow, so no API token is stored anywhere.

`Publish to PyPI` 工作流使用 PyPI 的"可信发布"：PyPI 直接信任本仓库的工作流，
仓库里不保存任何 API token。

1. Sign in to <https://pypi.org> (create an account and turn on two-factor
   authentication if needed).
   登录 PyPI（没有账号就注册，并按要求开启两步验证）。
2. Open **Your account → Publishing → Add a new pending publisher → GitHub**
   and enter:
   打开 **Your account → Publishing → Add a new pending publisher → GitHub**，填写：

   | Field | Value |
   | --- | --- |
   | PyPI Project Name | `code-art-studio` |
   | Owner | `nukofish` |
   | Repository name | `ascii-art-executable` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

3. Optional: in GitHub **Settings → Environments → New environment**, create
   `pypi` and add required reviewers, so every upload waits for a person.
   可选：在 GitHub 仓库 **Settings → Environments** 新建 `pypi` 环境并设置
   审核人，每次上传前都要有人批准。

## Release a version / 发布一个版本

1. Set `__version__` in `codeart/__init__.py` (for example `0.2.0`) and merge
   the change to `main`. PyPI never accepts the same version twice.
   修改 `codeart/__init__.py` 里的 `__version__` 并合并到 `main`。同一版本号
   在 PyPI 上只能上传一次。
2. On GitHub, open **Releases → Draft a new release**, create the tag
   `v0.2.0` on `main` (it must equal `v` + `__version__`), and publish it.
   在 GitHub 上打开 **Releases → Draft a new release**，在 `main` 上新建标签
   `v0.2.0`（必须等于 `v` + `__version__`），然后发布。
3. The workflow builds the wheel and source archive and uploads them. Check
   <https://pypi.org/project/code-art-studio/>, then test in a new
   environment:
   工作流会构建并上传。上传后打开上面的 PyPI 页面确认，再在新环境里测试：

   ```sh
   pip install code-art-studio==0.2.0
   codeart --sample gcd --shape cat > /dev/null
   ```

## Manual upload / 手动上传

Without the workflow, build and upload from a clean checkout of the tag. Paste
a PyPI API token (scoped to this project) when `twine` asks for a password,
with `__token__` as the user name. Never commit the token.

不用工作流时，在该标签的干净检出里构建并上传。`twine` 询问时，用户名填
`__token__`，密码粘贴只限本项目的 PyPI API token。不要把 token 提交到仓库。

```sh
python -m pip install build twine
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```
